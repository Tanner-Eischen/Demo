# GameDevBoard

GameDevBoard is a collaborative 2D map editor for game teams. It combines tile painting, sprite placement, physics configuration, and AI-assisted generation in one workflow, with real-time multiplayer editing.

## Why This Project Exists

Traditional level design tools often split map editing, collaboration, and gameplay metadata across separate tools. GameDevBoard brings those responsibilities together so teams can iterate on playable level concepts faster.

## Core Features

- Real-time collaborative board editing with presence and live synchronization.
- Tile-based map authoring with layer support and auto-tiling logic.
- Multiple tileset styles, including single tile, variant, multi-tile object, and auto-tile workflows.
- Sprite placement and sprite-definition management with animation state support.
- Physics-aware level authoring for platforms, collisions, hazards, and material behavior.
- AI-assisted terrain and layout generation through natural language chat.
- Multi-project and multi-board organization with save/load/export flows.
- Drawing and editor tools such as brush, shape tools, selection, pan/zoom, and undo/redo.

## Architecture Choices

### 1) Shared Type-Safe Domain Model

- `shared/schema.ts` centralizes database schema and shared types.
- This keeps client/server contracts aligned and reduces drift between API payloads and persisted data.
- Drizzle ORM is used for typed schema and migration workflows.

### 2) Split Frontend + Backend with Clear Boundaries

- `client/` contains the React editor UI and interaction logic.
- `server/` contains API routes, persistence, auth/middleware, and AI orchestration.
- `shared/` holds cross-cutting types and schema that both sides import.

This structure makes it easier to evolve editor UX without mixing backend concerns into UI code.

### 3) Real-Time Collaboration Model

- Collaboration uses WebSocket-based sync with Y.js CRDT tooling.
- CRDT synchronization supports concurrent edits with conflict-resistant merging behavior.
- Presence/awareness is surfaced in the editor to improve team coordination.

### 4) Canvas-Oriented Rendering and Interaction

- The board editor uses Konva/React-Konva to handle large interactive map surfaces.
- This provides a practical balance of rendering performance and ergonomic React integration for transform-heavy editor workflows.

### 5) AI via Structured Function Calling

- AI features are implemented server-side using OpenAI integration and function-oriented execution paths.
- Natural-language prompts are translated into deterministic editor actions (terrain paint, pattern generation, level scaffolding).
- Keeping AI logic server-side protects keys and allows guardrails around generated actions.

### 6) State and Data Strategy

- Zustand manages local editor state (tooling, canvas state, history interactions).
- React Query manages server-state fetching/caching and async synchronization.
- This separates high-frequency local interaction state from network-backed resource state.

## Tech Stack

- Frontend: React, TypeScript, Vite, Tailwind CSS, Radix UI, React Query, Zustand, Konva.
- Backend: Node.js, Express, TypeScript, WebSocket/Socket tooling.
- Data: PostgreSQL + Drizzle ORM.
- AI: OpenAI API with server-side orchestration.
