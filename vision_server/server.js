/**
 * Vision MCP Bridge Server
 * Uses Z.ai MCP server via stdio for vision analysis
 */
import express from 'express';
import multer from 'multer';
import { spawn } from 'child_process';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { randomUUID } from 'crypto';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const upload = multer({ dest: 'uploads/' });

const PORT = process.env.VISION_PORT || 8005;
const Z_AI_API_KEY = process.env.Z_AI_API_KEY;
const Z_AI_MODE = process.env.Z_AI_MODE || 'ZAI';

if (!Z_AI_API_KEY) {
  console.error('ERROR: Z_AI_API_KEY environment variable is required');
  process.exit(1);
}

app.use(express.json({ limit: '500mb' }));

// MCP server process (lazy loaded)
let mcpProcess = null;
let requestId = 0;
let pendingRequests = new Map();

/**
 * Start or get the MCP server process
 */
function getMcpProcess() {
  return new Promise((resolve, reject) => {
    if (mcpProcess && !mcpProcess.killed) {
      resolve(mcpProcess);
      return;
    }

    console.log('Starting MCP server...');
    mcpProcess = spawn('npx', ['-y', '@z_ai/mcp-server'], {
      env: {
        ...process.env,
        Z_AI_API_KEY,
        Z_AI_MODE
      },
      stdio: ['pipe', 'pipe', 'pipe'],
      shell: true
    });

    let buffer = '';
    mcpProcess.stdout.on('data', (data) => {
      buffer += data.toString();
      // MCP uses newline-delimited JSON
      const lines = buffer.split('\n');
      buffer = lines.pop(); // Keep incomplete line

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const response = JSON.parse(line);
          const resolver = pendingRequests.get(response.id);
          if (resolver) {
            pendingRequests.delete(response.id);
            resolver(response);
          }
        } catch (e) {
          // Not JSON, might be a log line
          console.log('MCP stdout:', line);
        }
      }
    });

    mcpProcess.stderr.on('data', (data) => {
      console.log('MCP stderr:', data.toString());
    });

    mcpProcess.on('error', (err) => {
      console.error('MCP process error:', err);
      mcpProcess = null;
    });

    mcpProcess.on('close', (code) => {
      console.log('MCP process closed with code:', code);
      mcpProcess = null;
    });

    // Initialize MCP connection
    setTimeout(() => resolve(mcpProcess), 1000);
  });
}

/**
 * Send a request to MCP server and wait for response
 */
async function mcpRequest(method, params = {}) {
  const proc = await getMcpProcess();
  const id = ++requestId;

  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pendingRequests.delete(id);
      reject(new Error('MCP request timeout'));
    }, 60000);

    pendingRequests.set(id, (response) => {
      clearTimeout(timeout);
      if (response.error) {
        reject(new Error(response.error.message || 'MCP error'));
      } else {
        resolve(response.result);
      }
    });

    const request = JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n';
    proc.stdin.write(request);
  });
}

/**
 * Call MCP tool
 */
async function callMcpTool(toolName, args) {
  return mcpRequest('tools/call', { name: toolName, arguments: args });
}

/**
 * Analyze image using MCP image_analysis tool
 */
async function analyzeImageViaMcp(imageSource, prompt) {
  try {
    const result = await callMcpTool('analyze_image', {
      image_source: imageSource,
      prompt
    });
    return result;
  } catch (err) {
    console.error('MCP image_analysis error:', err);
    throw err;
  }
}

/**
 * Analyze an image and return narration-ready description
 * POST /analyze
 */
app.post('/analyze', upload.single('image'), async (req, res) => {
  try {
    let imageSource;
    let prompt = req.body.prompt || 'Analyze this screenshot for a video narration. Describe what is shown and what action is being demonstrated.';
    let cleanupFile = null;

    if (req.file) {
      // Multer saves to temp file without extension - need to add it
      const ext = path.extname(req.file.originalname || '').toLowerCase();
      const correctExt = ext === '.png' ? '.png' : '.jpg';
      const newPath = req.file.path + correctExt;
      await fs.rename(req.file.path, newPath);
      imageSource = path.resolve(newPath);
      cleanupFile = imageSource;
    } else if (req.body.image) {
      const imageData = req.body.image;
      if (imageData.startsWith('http://') || imageData.startsWith('https://')) {
        // Already a URL
        imageSource = imageData;
      } else if (imageData.startsWith('data:')) {
        // Data URL - save to temp file
        const matches = imageData.match(/^data:image\/(\w+);base64,(.+)$/);
        if (matches) {
          const ext = matches[1] === 'png' ? 'png' : 'jpg';
          const buffer = Buffer.from(matches[2], 'base64');
          const tempPath = path.join(__dirname, 'uploads', `temp_${randomUUID()}.${ext}`);
          await fs.writeFile(tempPath, buffer);
          imageSource = tempPath;
          cleanupFile = tempPath;
        } else {
          return res.status(400).json({ error: 'Invalid data URL format' });
        }
      } else {
        // Raw base64 - save to temp file
        const buffer = Buffer.from(imageData, 'base64');
        const tempPath = path.join(__dirname, 'uploads', `temp_${randomUUID()}.jpg`);
        await fs.writeFile(tempPath, buffer);
        imageSource = tempPath;
        cleanupFile = tempPath;
      }
    } else {
      return res.status(400).json({ error: 'No image provided' });
    }

    const result = await analyzeImageViaMcp(imageSource, prompt);

    // Cleanup temp file after analysis
    if (cleanupFile) {
      await fs.unlink(cleanupFile).catch(() => {});
    }

    res.json(result);

  } catch (error) {
    console.error('Analysis error:', error);
    res.status(500).json({ error: error.message });
  }
});

/**
 * Analyze segment for narration
 * POST /analyze-segment
 */
app.post('/analyze-segment', async (req, res) => {
  try {
    const { images, segment_id, start_ms, end_ms, project_context } = req.body;

    if (!images || !Array.isArray(images) || images.length === 0) {
      return res.status(400).json({ error: 'No images provided' });
    }

    const duration_s = ((end_ms || 0) - (start_ms || 0)) / 1000;

    const contextBlock = project_context
      ? `Project Context:
${project_context}

`
      : '';

    const prompt = `Analyze this screenshot for a FIRST-PERSON video narration script.

${contextBlock}CONTEXT: This is segment ${segment_id || 0} of a software demo video (${duration_s.toFixed(1)} seconds).

TASK: Write AS IF YOU ARE THE CREATOR demonstrating your own app in a demo video.
- Use "I" and "my" language
- Present tense, conversational tone
- IMPORTANT: When project context is provided, incorporate insights about WHY this feature matters, what problem it solves, or its impact - not just WHAT is visible
- Balance between describing the action AND explaining its significance
- If context mentions specific benefits, use cases, or technical details, weave them naturally into the narration

EXAMPLE STYLE with context: "Here's the real-time collaboration feature that lets multiple developers work on the same level simultaneously - this solves the coordination nightmare of team game development."

EXAMPLE STYLE without context: "Here I'm showing you the collaboration panel. Team members can edit together."

NARRATION PRIORITIES (in order):
1. If context explains WHY this feature exists or what problem it solves -> include that insight
2. If context mentions technical details or architecture -> briefly reference it
3. If context describes user benefits or use cases -> mention the value proposition
4. Otherwise, describe what's visible and the action being taken

Project constraints:
- Use project context to add depth and meaning, not just as background
- Never contradict what is visible in frames
- Do not invent features not mentioned in context or visible on screen

Respond in JSON format:
{
  "ui_context": {"app_guess": "<app name if detectable>", "page_title": "<page/section>", "primary_region": "<main UI area>"},
  "actions": [{"type": "<click/type/scroll/etc>", "target": "<element>", "description": "<what happened>"}],
  "result": "<summary of what was accomplished and why it matters>",
  "on_screen_text": ["<visible text elements>"],
  "narration_candidates": ["<narration with context insight 1>", "<narration with context insight 2>"]
}`;

    // Process first image - handle data URLs and base64
    let imageSource = images[0];
    let cleanupFile = null;

    if (imageSource.startsWith('http://') || imageSource.startsWith('https://')) {
      // Already a URL - use directly
    } else if (imageSource.startsWith('data:')) {
      // Data URL - save to temp file
      const matches = imageSource.match(/^data:image\/(\w+);base64,(.+)$/);
      if (matches) {
        const ext = matches[1] === 'png' ? 'png' : 'jpg';
        const buffer = Buffer.from(matches[2], 'base64');
        const tempPath = path.join(__dirname, 'uploads', `temp_${randomUUID()}.${ext}`);
        await fs.writeFile(tempPath, buffer);
        imageSource = tempPath;
        cleanupFile = tempPath;
      }
    } else {
      // Raw base64 - save to temp file
      const buffer = Buffer.from(imageSource, 'base64');
      const tempPath = path.join(__dirname, 'uploads', `temp_${randomUUID()}.jpg`);
      await fs.writeFile(tempPath, buffer);
      imageSource = tempPath;
      cleanupFile = tempPath;
    }

    const result = await analyzeImageViaMcp(imageSource, prompt);

    // Cleanup temp file
    if (cleanupFile) {
      await fs.unlink(cleanupFile).catch(() => {});
    }

    // Parse result if it's a string
    let parsed = result;
    if (typeof result === 'string') {
      try {
        parsed = JSON.parse(result);
      } catch {
        // Try to extract JSON from markdown
        const match = result.match(/```(?:json)?\s*([\s\S]*?)```/);
        if (match) {
          try { parsed = JSON.parse(match[1].trim()); } catch {}
        }
        if (typeof parsed === 'string') {
          parsed = { narration_candidates: [result], result: result };
        }
      }
    }

    // Handle MCP tool response format
    if (parsed.content && Array.isArray(parsed.content)) {
      const textContent = parsed.content.find(c => c.type === 'text');
      if (textContent) {
        try {
          parsed = JSON.parse(textContent.text);
        } catch {
          parsed = { narration_candidates: [textContent.text], result: textContent.text };
        }
      }
    }

    const response = {
      segment_id: segment_id || 0,
      ui_context: parsed.ui_context || { app_guess: '', page_title: '', primary_region: '' },
      actions: parsed.actions || [],
      result: parsed.result || '',
      on_screen_text: parsed.on_screen_text || [],
      narration_candidates: parsed.narration_candidates || [parsed.description || parsed.result || 'Continue the demo.']
    };

    res.json(response);

  } catch (error) {
    console.error('Segment analysis error:', error);
    res.status(500).json({ error: error.message });
  }
});

/**
 * Match narration text to the best keyframe
 * POST /match-narration
 *
 * Input: { narration_text, keyframe_images[], keyframe_times_ms[] }
 * Output: { best_keyframe_index, confidence, visual_context, reasoning }
 */
app.post('/match-narration', async (req, res) => {
  try {
    const { narration_text, keyframe_images, keyframe_times_ms, section_id, project_context } = req.body;

    if (!narration_text || typeof narration_text !== 'string') {
      return res.status(400).json({ error: 'narration_text is required' });
    }

    if (!keyframe_images || !Array.isArray(keyframe_images) || keyframe_images.length === 0) {
      return res.status(400).json({ error: 'keyframe_images array is required' });
    }

    if (!keyframe_times_ms || !Array.isArray(keyframe_times_ms) || keyframe_times_ms.length !== keyframe_images.length) {
      return res.status(400).json({ error: 'keyframe_times_ms array must match keyframe_images length' });
    }

    const contextBlock = project_context
      ? `Project Context:
${project_context}

`
      : '';

    // Build prompt asking where this narration fits best
    const prompt = `${contextBlock}TASK: Find the BEST visual match for this narration text.

NARRATION TEXT:
"${narration_text}"

I will show you ${keyframe_images.length} keyframes from different points in the video.
For each keyframe, consider:
1. How well does the visual content match what the narration describes?
2. Would this narration make sense at this point in the video?
3. Is the timing appropriate for this content?

OUTPUT SCHEMA (strict JSON):
{
  "best_keyframe_index": 0,
  "confidence": 0.85,
  "visual_context": "What you see in the best matching frame",
  "reasoning": "Why this frame matches the narration best",
  "alternatives": [
    {"index": 1, "confidence": 0.7, "reasoning": "Secondary match"}
  ]
}

RULES:
- confidence: 0.0 to 1.0 (how confident you are in the match)
- best_keyframe_index: index of the best matching keyframe (0-based)
- If no frame is a good match, still pick the best one but lower confidence
- Consider the FLOW of a demo video: intro -> features -> details -> conclusion
- Be honest about confidence - low confidence is okay

Respond with ONLY valid JSON, no markdown formatting.`;

    // Process images and build content array
    const content = [];
    let cleanupFiles = [];

    for (let i = 0; i < keyframe_images.length; i++) {
      const imageData = keyframe_images[i];
      const timestamp = keyframe_times_ms[i];
      let imageSource = imageData;

      try {
        if (imageData.startsWith('http://') || imageData.startsWith('https://')) {
          // Already a URL - use directly
          imageSource = imageData;
        } else if (imageData.startsWith('data:')) {
          // Data URL - save to temp file
          const matches = imageData.match(/^data:image\/(\w+);base64,(.+)$/);
          if (matches) {
            const ext = matches[1] === 'png' ? 'png' : 'jpg';
            const buffer = Buffer.from(matches[2], 'base64');
            const tempPath = path.join(__dirname, 'uploads', `match_${randomUUID()}.${ext}`);
            await fs.writeFile(tempPath, buffer);
            imageSource = tempPath;
            cleanupFiles.push(tempPath);
          }
        } else {
          // Raw base64 - save to temp file
          const buffer = Buffer.from(imageData, 'base64');
          const tempPath = path.join(__dirname, 'uploads', `match_${randomUUID()}.jpg`);
          await fs.writeFile(tempPath, buffer);
          imageSource = tempPath;
          cleanupFiles.push(tempPath);
        }

        content.push({
          type: 'text',
          text: `Keyframe ${i} at ${timestamp}ms:`
        });
        content.push({
          type: 'image_url',
          image_url: { url: imageSource }
        });
      } catch (err) {
        console.error(`Error processing keyframe ${i}:`, err);
      }
    }

    content.push({ type: 'text', text: prompt });

    // Call vision model
    let result;
    try {
      result = await callMcpTool('analyze_image', {
        image_source: content[1]?.image_url?.url || keyframe_images[0],
        prompt: prompt
      });
    } catch (mcpError) {
      // Fallback: process images one at a time for matching
      console.log('MCP analyze_image failed, using sequential matching:', mcpError.message);

      let bestMatch = { best_keyframe_index: 0, confidence: 0.3, visual_context: '', reasoning: 'Fallback match' };

      for (let i = 0; i < Math.min(keyframe_images.length, 5); i++) {
        try {
          const imgPath = content[i * 2 + 1]?.image_url?.url || keyframe_images[i];
          const singlePrompt = `Does this screenshot match this narration: "${narration_text}"?
Rate the match quality from 0.0 to 1.0.
Respond with ONLY a JSON object: {"match_score": 0.85, "reasoning": "why"}`;

          const singleResult = await analyzeImageViaMcp(imgPath, singlePrompt);
          let parsed = singleResult;
          if (typeof singleResult === 'string') {
            try { parsed = JSON.parse(singleResult); } catch {}
          }
          if (parsed?.content?.[0]?.type === 'text') {
            try { parsed = JSON.parse(parsed.content[0].text); } catch {}
          }

          const score = parsed?.match_score || 0.3;
          if (score > bestMatch.confidence) {
            bestMatch = {
              best_keyframe_index: i,
              confidence: score,
              visual_context: parsed?.visual_context || '',
              reasoning: parsed?.reasoning || 'Sequential match'
            };
          }
        } catch (e) {
          console.error(`Error matching keyframe ${i}:`, e);
        }
      }

      result = bestMatch;
    }

    // Cleanup temp files
    for (const file of cleanupFiles) {
      await fs.unlink(file).catch(() => {});
    }

    // Parse result
    let parsed = result;
    if (typeof result === 'string') {
      try {
        parsed = JSON.parse(result);
      } catch {
        const match = result.match(/```(?:json)?\s*([\s\S]*?)```/);
        if (match) {
          try { parsed = JSON.parse(match[1].trim()); } catch {}
        }
        if (typeof parsed === 'string') {
          parsed = { best_keyframe_index: 0, confidence: 0.3, visual_context: result, reasoning: 'Could not parse' };
        }
      }
    }

    // Handle MCP tool response format
    if (parsed?.content && Array.isArray(parsed.content)) {
      const textContent = parsed.content.find(c => c.type === 'text');
      if (textContent) {
        try {
          parsed = JSON.parse(textContent.text);
        } catch {
          parsed = { best_keyframe_index: 0, confidence: 0.3, visual_context: textContent.text, reasoning: 'Parsed from text' };
        }
      }
    }

    const response = {
      section_id: section_id ?? 0,
      best_keyframe_index: parsed?.best_keyframe_index ?? 0,
      confidence: parsed?.confidence ?? 0.3,
      visual_context: parsed?.visual_context ?? '',
      reasoning: parsed?.reasoning ?? 'Default match',
      alternatives: parsed?.alternatives ?? []
    };

    res.json(response);

  } catch (error) {
    console.error('Match narration error:', error);
    res.status(500).json({ error: error.message });
  }
});

/**
 * Chat completion via MCP
 * POST /chat
 */
app.post('/chat', async (req, res) => {
  try {
    const { model, messages, temperature, max_tokens } = req.body;

    if (!messages || !Array.isArray(messages)) {
      return res.status(400).json({ error: 'messages array required' });
    }

    // Build prompt from messages
    const systemMsg = messages.find(m => m.role === 'system');
    const userMsgs = messages.filter(m => m.role === 'user');

    let prompt = '';
    if (systemMsg) {
      prompt += systemMsg.content + '\n\n';
    }

    for (const msg of userMsgs) {
      if (typeof msg.content === 'string') {
        prompt += msg.content + '\n';
      } else if (Array.isArray(msg.content)) {
        // Handle multimodal content - extract text
        for (const part of msg.content) {
          if (part.type === 'text') {
            prompt += part.text + '\n';
          }
        }
      }
    }

    // Try using MCP chat tool if available
    try {
      const result = await callMcpTool('chat', {
        model: model || 'glm-5',
        prompt: prompt.trim(),
        temperature: temperature || 0.3,
        max_tokens: max_tokens || 2048
      });

      // Parse MCP response
      let responseText = result;
      if (result && result.content && Array.isArray(result.content)) {
        const textContent = result.content.find(c => c.type === 'text');
        if (textContent) {
          responseText = textContent.text;
        }
      }

      res.json({
        choices: [{
          message: { role: 'assistant', content: responseText }
        }]
      });
      return;
    } catch (mcpError) {
      console.log('MCP chat tool not available, falling back to analysis:', mcpError.message);
    }

    // Fallback: use analyze_image with a text-only prompt
    // This is a workaround since MCP may not have a direct chat tool
    try {
      const result = await callMcpTool('analyze_image', {
        image_source: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
        prompt: prompt.trim()
      });

      let responseText = result;
      if (result && result.content && Array.isArray(result.content)) {
        const textContent = result.content.find(c => c.type === 'text');
        if (textContent) {
          responseText = textContent.text;
        }
      }

      // Check if the response contains an error about image
      if (typeof responseText === 'string' && responseText.toLowerCase().includes('error')) {
        throw new Error('MCP analyze_image fallback failed: ' + responseText);
      }

      res.json({
        choices: [{
          message: { role: 'assistant', content: responseText }
        }]
      });
      return;
    } catch (fallbackError) {
      console.log('Fallback also failed:', fallbackError.message);
      // Return error so client can fall back to direct API
      return res.status(502).json({ error: 'MCP chat unavailable: ' + fallbackError.message });
    }

    res.json({
      choices: [{
        message: { role: 'assistant', content: responseText }
      }]
    });

  } catch (error) {
    console.error('Chat error:', error);
    res.status(500).json({ error: error.message });
  }
});

// Health check
app.get('/health', (req, res) => {
  res.json({
    ok: true,
    service: 'vision-mcp-bridge',
    mcp_connected: mcpProcess && !mcpProcess.killed
  });
});

// Graceful shutdown
process.on('SIGINT', () => {
  if (mcpProcess) {
    mcpProcess.kill();
  }
  process.exit(0);
});

app.listen(PORT, () => {
  console.log(`Vision MCP Bridge running on http://localhost:${PORT}`);
  console.log(`Using Z.ai MCP Server with API key: ${Z_AI_API_KEY.substring(0, 8)}...`);
  console.log(`Endpoints:`);
  console.log(`  POST /analyze          - Analyze single image`);
  console.log(`  POST /analyze-segment  - Analyze for segment narration`);
  console.log(`  POST /match-narration  - Match narration to best keyframe`);
  console.log(`  GET  /health           - Health check`);
});
