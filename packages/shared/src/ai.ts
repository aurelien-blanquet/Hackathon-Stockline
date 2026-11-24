/**
 * Contract of the AI service (apps/ai, default http://localhost:4100).
 *
 *  GET  /health                         → { ok, llm: {provider, model}, stt: {provider}, tts: {provider} }
 *  GET  /tools                          → ToolInfo[]  (tools the harness exposes to the model)
 *  POST /chat                           body ChatRequest → text/event-stream of ChatStreamEvent (one JSON per `data:` line)
 *  WS   /voice                          bidirectional, see VoiceClientMessage / VoiceServerMessage
 *  POST /stt                            raw audio body (audio/webm | audio/wav) → { text, ms }
 *  POST /tts                            body { text, voice? } → audio bytes (audio/mpeg or audio/wav), header x-ms
 *  POST /command[?speak=1]              single-turn voice COMMAND (stateless, act-first, one-line answer).
 *                                       body = raw audio (content-type audio/webm|wav…, header x-mock-text for the mock STT)
 *                                       or JSON { text, actorName? } → text/event-stream of CommandStreamEvent:
 *                                       transcript → (text | tool_call | tool_result)* → navigate? → speech? → done (with timings) | error.
 *                                       speak=1 → a `speech` event (base64 audio; MOCK_TTS_MIME = speak the text in the browser).
 *  WS   /voice/command[?speak=1]        the same command with LIVE transcription: send audio_start {mime, hint?}, binary frames
 *                                       while the key is down, audio_end (or one { type: "text" }); receive CommandStreamEvent JSON
 *                                       (transcript final=false while speaking, then the POST /command events). Closed after done | error.
 */

export type ChatRole = "system" | "user" | "assistant" | "tool";

export interface ChatMessage {
  role: ChatRole;
  content: string;
  toolCallId?: string; // for role "tool"
  toolCalls?: ToolCall[]; // for role "assistant"
  name?: string;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface ToolInfo {
  name: string;
  description: string;
  parameters: Record<string, unknown>; // JSON schema
}

export interface ChatRequest {
  messages: ChatMessage[]; // full conversation so far (no system message; the harness adds it)
  mode?: "chat" | "voice" | "command"; // voice → short spoken-style answers; command → single-turn, act-first, one line
  actorName?: string;
}

export type ChatStreamEvent =
  | { type: "text"; delta: string }
  | { type: "tool_call"; call: ToolCall }
  | { type: "tool_result"; callId: string; name: string; ok: boolean; result: unknown; ms: number }
  | { type: "done"; message: ChatMessage; usage?: { inputTokens?: number; outputTokens?: number; cacheCreationInputTokens?: number; cacheReadInputTokens?: number }; ms: number; timings?: TurnTimings }
  | { type: "error"; message: string };

// ── Voice (push-to-talk, two tracks: the human "caller" and the agent) ──

export type VoiceClientMessage =
  | { type: "start"; sessionId?: string; actorName?: string } // opens a conversation
  | { type: "audio_start"; mime: string; hint?: string } // caller pressed space (hint: optional STT vocabulary; mock STT returns it)
  | { type: "audio_end" } // caller released space; binary frames sent in between (every 100–250 ms) are the utterance, streamed to the STT as they arrive
  | { type: "text"; text: string } // typed instead of spoken (debug)
  | { type: "reset" };

/** One tool call of a voice turn (model or fast path). */
export interface ToolTiming { name: string; startMs: number; ms: number }

/** Latency of one turn (ms). Unless said otherwise, from the END of the caller's speech as the server sees it. */
export interface TurnTimings {
  sttMs?: number; // end of speech → final transcript
  llmFirstTokenMs?: number; // model call start → first model output (text or tool call)
  llmTotalMs?: number;
  ttsFirstByteMs?: number;
  totalMs?: number; // end of caller speech → first agent audio byte (acknowledgement included)
  // diagnosis
  sttConnectMs?: number; // START of speech → live STT stream ready
  sttBacklogFrames?: number; // audio frames not yet sent to the STT when the speech ended
  sttFinalizeSentMs?: number; // end of speech → all audio sent + finalize sent
  sttFallback?: boolean; // live stream failed: the whole recording was re-transcribed
  ackAudioMs?: number; // end of speech → first acknowledgement / filler audio byte sent
  usefulTextMs?: number; // end of speech → first word of the real answer
  usefulAudioMs?: number; // end of speech → first audio byte of the real answer sent
  tools?: ToolTiming[];
  llmModel?: string; // model that answered (and whether the answer was prepared while the caller spoke)
}

/** The TurnTimings fields that are durations in ms (for latency chips). */
export type TurnTimingMs = { [K in keyof TurnTimings]-?: NonNullable<TurnTimings[K]> extends number ? K : never }[keyof TurnTimings];

/** One line of the customer-facing offer card (no supplier, cost, margin or internal id). */
export interface OfferLine {
  product: string;
  qty?: number | null; // null: the caller has not said how much yet
  unit?: string | null;
  unitPrice?: number | null; // the caller's own price, EUR excl. VAT
  total?: number | null;
  availability: string; // « En stock », « 851 pièces en stock, le reste arrive demain », « À préciser »
  delivery?: string | null;
  options?: string[] | null; // variants to choose from when the product is ambiguous
}

/** « Le comité de prix »: four agents' findings, the options (with margins) and the decision. Staff screen only. */
export interface DealOption {
  key: string; qty: number; unit: string; pct: number; unitPrice: number; listUnitPrice: number; total: number;
  margin: number; wasteAvoided: number; pAccept: number; expected: number; why: string;
}
export interface DealPanel {
  dealId: string; product: string; askedQty: number; ms: number;
  agents: { name: string; line: string; ms: number }[];
  options: DealOption[]; chosen: string; alternative?: string | null; decision: string;
}

export type VoiceServerMessage =
  | { type: "ready"; sessionId: string; stt: string; tts: string; llm: string }
  // While the caller speaks (streaming STT): final=false, the whole text heard so far, resent as words are recognised;
  // `stable` = its leading part made of final words (won't change). Then once final=true: what the agent answers.
  | { type: "transcript"; track: "caller"; text: string; final: boolean; stable?: string }
  | { type: "agent_text"; delta: string }
  | { type: "agent_tool"; name: string; ok?: boolean; ms?: number; args?: Record<string, unknown> }
  | { type: "agent_status"; label: string } // what the side agents are doing (« Recherche des offres… »)
  | { type: "agent_offer"; lines: OfferLine[] } // the best offer found this turn (replaces the previous card)
  | { type: "customer_message"; channel: string; to: string; text: string } // written recap sent at confirmation
  | { type: "agent_deal"; panel?: DealPanel | null } // « Le comité de prix »; null: the four agents are working
  | { type: "agent_audio_start"; mime: string } // binary frames follow
  | { type: "agent_audio_mark"; kind: "useful" } // the next audio bytes are the real answer (before: acknowledgement)
  | { type: "agent_audio_end" }
  | { type: "agent_done"; text: string; timings: TurnTimings }
  | { type: "error"; message: string };

/**
 * Mime returned by the AI service's mock TTS (no key configured): the bytes are a short silent WAV.
 * Clients should ignore the audio and speak the agent text with the browser's speechSynthesis instead.
 */
export const MOCK_TTS_MIME = "audio/x-mock-wav";

// ── Voice command (POST /command: one utterance → one action → one line) ──

/** JSON body of POST /command (or send raw audio instead). */
export interface CommandRequest {
  text: string;
  actorName?: string;
}

export type CommandStreamEvent =
  | ChatStreamEvent
  // final (default true) comes before the agent's events; ms = STT time, 0 for typed text.
  // WS /ai/voice/command also sends final=false ones while the user speaks (text so far, `stable` = final words).
  | { type: "transcript"; text: string; ms: number; final?: boolean; stable?: string }
  | { type: "navigate"; path: string; label?: string } // the user asked to SEE an entity: web route to open (e.g. /products/prd_0012)
  | { type: "speech"; mime: string; audio: string; ms: number }; // ?speak=1: base64 audio of the answer; mime MOCK_TTS_MIME → speechSynthesis
