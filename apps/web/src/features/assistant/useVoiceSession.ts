/**
 * Push-to-talk voice session over WS /ai/voice (contract: VoiceClientMessage / VoiceServerMessage in @kit/shared).
 * Mic → MediaRecorder (webm/opus) chunks every 100 ms, streamed as binary frames between audio_start and audio_end:
 * the server transcribes them as they arrive and sends `transcript` final:false (live text) before the final one.
 * Agent audio: binary frames between agent_audio_start/end → one Blob → <audio>. Mock TTS → speechSynthesis (fr-FR).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { MOCK_TTS_MIME, type DealPanel, type OfferLine, type TurnTimings, type VoiceClientMessage, type VoiceServerMessage } from "@kit/shared";
import { AI_BASE } from "@/lib/api";
import { PcmPlayer, SegmentPlayer, audioContext } from "./audio-player";
import type { ToolRun } from "./tools";

export type Conn = "connecting" | "ready" | "offline";
export type Activity = "idle" | "recording" | "thinking" | "speaking";
export type MicState = "unknown" | "granted" | "denied" | "unsupported";

export interface VoiceTurn {
  id: number;
  /** text: live while recording/transcribing (stable = its final words), definitive once status is "final". */
  caller: { text: string; stable?: string; at: number; status: "recording" | "transcribing" | "final"; typed?: boolean };
  agent: {
    text: string; at?: number; tools: ToolRun[]; done: boolean; error?: string; interrupted?: boolean;
    /** Side agents' progress (« Recherche des offres… ») and the customer-facing offer card. */
    status?: string; offer?: OfferLine[]; sent?: { channel: string; to: string; text: string };
  };
  timings?: TurnTimings;
  /** Client-side: caller release → agent audio actually starts playing (or speech synthesis starts): the FIRST sound,
   *  often the acknowledgement (« D'accord. »). */
  perceivedMs?: number;
  /** Client clock, from the key release: when the audio header / first audio bytes arrived, and which player played it. */
  client?: { firstTextMs?: number; audioStartMs?: number; firstChunkMs?: number; player?: "PCM" | "mp3" };
  /** Client-side: caller release → the REAL answer starts playing (after the acknowledgement, if any). */
  usefulPerceivedMs?: number;
  /** Client-side: caller release → final transcript received (mic tail + upload + STT finalize + network). */
  transcriptMs?: number;
}

export interface Providers { llm: string; stt: string; tts: string; sessionId: string }

const REC_MIME = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
// Keep recording a little after Space is released: people let go while still saying the last word (often the
// quantity or the product), and MediaRecorder would cut it off.
const RELEASE_TAIL_MS = 150; // mar. 19:45: 200 → 150 ms (no cut word seen with Soniox; the tail is on every turn)
const MIC_CONSTRAINTS: MediaTrackConstraints = { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 };
const wsUrl = () => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${AI_BASE}/voice`;

export function useVoiceSession() {
  const [conn, setConn] = useState<Conn>("connecting");
  const [activity, setActivity] = useState<Activity>("idle");
  const [mic, setMic] = useState<MicState>("unknown");
  const [providers, setProviders] = useState<Providers>();
  const [turns, setTurns] = useState<VoiceTurn[]>([]);
  const [level, setLevel] = useState(0);
  const [lastError, setLastError] = useState<string>();
  /** « Le comité de prix »: undefined = none yet, "working" = the four agents run, else the last decision. */
  const [deal, setDeal] = useState<DealPanel | "working">();

  const ws = useRef<WebSocket>();
  const sessionId = useRef<string>();
  const alive = useRef(true);
  const turnSeq = useRef(0);
  const currentTurn = useRef<number>();
  // mic
  const stream = useRef<MediaStream>();
  const recorder = useRef<MediaRecorder>();
  const pressed = useRef(false);
  const tail = useRef<{ timer: ReturnType<typeof setTimeout>; rec: MediaRecorder }>(); // release tail in progress
  const audioCtx = useRef<AudioContext>();
  const analyser = useRef<AnalyserNode>();
  const raf = useRef<number>();
  // playback
  const player = useRef<SegmentPlayer | PcmPlayer>();
  const audioMime = useRef<string>();
  const discardAudio = useRef(false); // audio of an interrupted turn still draining
  const releasedAt = useRef<number>();
  const turnReleasedAt = useRef<number>(); // same instant, kept for the whole turn (releasedAt is cleared at first sound)
  const turnHasAudio = useRef(false);
  const pendingText = useRef<{ id: number | undefined; text: string }>(); // agent words not drawn yet (one frame)
  const textFrame = useRef(0);

  const patchTurn = useCallback((id: number | undefined, fn: (t: VoiceTurn) => VoiceTurn) => {
    if (id == null) return;
    setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)));
  }, []);

  const newTurn = useCallback((caller: VoiceTurn["caller"]) => {
    const id = ++turnSeq.current;
    const prev = currentTurn.current;
    currentTurn.current = id;
    turnHasAudio.current = false;
    audioMime.current = undefined;
    discardAudio.current = true;
    setTurns((ts) => [
      ...ts.map((t) => (t.id === prev && !t.agent.done ? { ...t, agent: { ...t.agent, done: true, interrupted: true } } : t)),
      { id, caller, agent: { text: "", tools: [], done: false } },
    ]);
    return id;
  }, []);

  const send = useCallback((m: VoiceClientMessage) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(m));
  }, []);

  // ── Playback ──
  const stopPlayback = useCallback(() => {
    try { window.speechSynthesis?.cancel(); } catch { /* ignore */ }
    const p = player.current;
    player.current = undefined;
    p?.stop();
    setActivity((a) => (a === "speaking" ? "idle" : a));
  }, []);

  const markPerceived = useCallback((id: number | undefined) => {
    const t0 = releasedAt.current;
    if (t0 == null) return;
    releasedAt.current = undefined;
    patchTurn(id, (t) => ({ ...t, perceivedMs: Math.round(performance.now() - t0) }));
  }, [patchTurn]);

  /** The real answer is heard (latency diagnosis): the playhead passed agent_audio_mark. */
  const markUsefulPerceived = useCallback((id: number | undefined) => {
    const t0 = turnReleasedAt.current;
    if (t0 == null) return;
    patchTurn(id, (t) => (t.usefulPerceivedMs != null ? t : { ...t, usefulPerceivedMs: Math.round(performance.now() - t0) }));
  }, [patchTurn]);

  const speak = useCallback((text: string, id: number | undefined) => {
    const synth = window.speechSynthesis;
    if (!synth || !text.trim()) { setActivity("idle"); return; }
    stopPlayback();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "fr-FR";
    const fr = synth.getVoices().find((v) => v.lang?.toLowerCase().startsWith("fr"));
    if (fr) u.voice = fr;
    u.rate = 1.08;
    u.onstart = () => { setActivity("speaking"); markPerceived(id); markUsefulPerceived(id); };
    u.onend = u.onerror = () => setActivity((a) => (a === "speaking" ? "idle" : a));
    setActivity("speaking");
    synth.speak(u);
  }, [markPerceived, markUsefulPerceived, stopPlayback]);

  // ── Server messages ──
  const onMessage = useCallback((ev: MessageEvent) => {
    if (typeof ev.data !== "string") {
      if (!discardAudio.current) {
        player.current?.push(ev.data as ArrayBuffer);
        const t0 = turnReleasedAt.current, id0 = currentTurn.current;
        if (t0 != null) patchTurn(id0, (t) => (t.client?.firstChunkMs != null ? t : { ...t, client: { ...t.client, firstChunkMs: Math.round(performance.now() - t0) } }));
      }
      return;
    }
    let m: VoiceServerMessage;
    try { m = JSON.parse(ev.data); } catch { return; }
    const id = currentTurn.current;
    switch (m.type) {
      case "ready":
        sessionId.current = m.sessionId;
        setProviders({ llm: m.llm, stt: m.stt, tts: m.tts, sessionId: m.sessionId });
        setConn("ready");
        break;
      case "transcript": {
        const turn = id;
        if (!m.final) {
          // Live partial while the caller speaks (or just after the release): never over a final text.
          patchTurn(turn, (t) => (t.caller.status === "final" ? t : { ...t, caller: { ...t.caller, text: m.text, stable: m.stable ?? "" } }));
          break;
        }
        // Typed turns already show the caller text; the server echoes it as a transcript.
        if (turn == null) newTurn({ text: m.text, at: Date.now(), status: "final" });
        else {
          const t0 = turnReleasedAt.current;
          const now = performance.now();
          patchTurn(turn, (t) => ({
            ...t,
            caller: { ...t.caller, text: m.text, status: "final" },
            ...(t0 != null && !t.caller.typed && t.transcriptMs == null ? { transcriptMs: Math.round(now - t0) } : {}),
          }));
        }
        setActivity((a) => (a === "recording" ? a : "thinking"));
        break;
      }
      case "agent_text":
        if (turnReleasedAt.current != null && m.delta.trim()) {
          const t0 = turnReleasedAt.current;
          patchTurn(id, (t) => (t.client?.firstTextMs != null ? t : { ...t, client: { ...t.client, firstTextMs: Math.round(performance.now() - t0) } }));
        }
        // batched: the words of one frame are added in one update (not one redraw per word)
        const prev = pendingText.current;
        pendingText.current = { id, text: (prev && prev.id === id ? prev.text : "") + m.delta };
        if (!textFrame.current) {
          textFrame.current = requestAnimationFrame(() => {
            textFrame.current = 0;
            const p = pendingText.current;
            pendingText.current = undefined;
            if (p) patchTurn(p.id, (t) => ({ ...t, agent: { ...t.agent, text: t.agent.text + p.text, at: t.agent.at ?? Date.now() } }));
          });
        }
        break;
      case "agent_tool":
        patchTurn(id, (t) => {
          const tools = [...t.agent.tools];
          if (m.ok === undefined) tools.push({ id: `${t.id}-${tools.length}`, name: m.name, args: m.args });
          else {
            const i = tools.findIndex((x) => x.name === m.name && x.ok === undefined);
            if (i >= 0) tools[i] = { ...tools[i], ok: m.ok, ms: m.ms };
            else tools.push({ id: `${t.id}-${tools.length}`, name: m.name, ok: m.ok, ms: m.ms });
          }
          return { ...t, agent: { ...t.agent, tools, at: t.agent.at ?? Date.now() } };
        });
        break;
      case "agent_status":
        patchTurn(id, (t) => ({ ...t, agent: { ...t.agent, status: m.label } }));
        break;
      case "customer_message":
        patchTurn(id, (t) => ({ ...t, agent: { ...t.agent, sent: { channel: m.channel, to: m.to, text: m.text } } }));
        break;
      case "agent_deal":
        setDeal(m.panel ?? "working");
        break;
      case "agent_offer":
        patchTurn(id, (t) => ({ ...t, agent: { ...t.agent, offer: m.lines } }));
        break;
      case "agent_audio_start":
        discardAudio.current = false;
        audioMime.current = m.mime;
        turnHasAudio.current = true;
        if (m.mime !== MOCK_TTS_MIME) {
          stopPlayback();
          const Player = m.mime.startsWith("audio/pcm") ? PcmPlayer : SegmentPlayer; // PCM: played as it arrives
          const t0 = turnReleasedAt.current;
          patchTurn(id, (t) => ({ ...t, client: { ...t.client, player: m.mime.startsWith("audio/pcm") ? "PCM" : "mp3",
            ...(t0 != null && t.client?.audioStartMs == null ? { audioStartMs: Math.round(performance.now() - t0) } : {}) } }));
          const p: SegmentPlayer | PcmPlayer = new Player(m.mime, {
            onPlaying: () => { setActivity("speaking"); markPerceived(id); },
            onUsefulPlaying: () => markUsefulPerceived(id),
            onEnded: () => {
              if (player.current === p) player.current = undefined;
              setActivity((a) => (a === "speaking" ? "idle" : a));
            },
          });
          player.current = p;
        }
        break;
      case "agent_audio_mark":
        if (!discardAudio.current) player.current?.markUseful();
        break;
      case "agent_audio_end":
        // An interrupted turn's segment closes after the new turn started: drop it.
        if (discardAudio.current) break;
        player.current?.end();
        break;
      case "agent_done":
        if (pendingText.current) { // words of the last frame: drawn before the turn closes
          const p = pendingText.current;
          pendingText.current = undefined;
          patchTurn(p.id, (t) => ({ ...t, agent: { ...t.agent, text: t.agent.text + p.text } }));
        }
        patchTurn(id, (t) => ({ ...t, timings: m.timings, agent: { ...t.agent, done: true, text: m.text || t.agent.text } }));  // what was said (server-filtered), not the raw stream
        if (audioMime.current === MOCK_TTS_MIME && turnHasAudio.current) speak(m.text, id);
        else if (!turnHasAudio.current || !player.current) setActivity((a) => (a === "thinking" ? "idle" : a));
        audioMime.current = undefined;
        currentTurn.current = undefined;
        break;
      case "error":
        setLastError(m.message);
        if (id != null) patchTurn(id, (t) => ({ ...t, caller: { ...t.caller, status: "final" }, agent: { ...t.agent, done: true, error: m.message } }));
        currentTurn.current = undefined;
        setActivity((a) => (a === "thinking" ? "idle" : a));
        break;
    }
  }, [markPerceived, markUsefulPerceived, newTurn, patchTurn, speak, stopPlayback]);

  // ── Connection (auto-reconnect, same sessionId keeps the server-side history) ──
  const connect = useCallback(() => {
    if (!alive.current) return;
    ws.current?.close();
    setConn("connecting");
    const sock = new WebSocket(wsUrl());
    sock.binaryType = "arraybuffer";
    ws.current = sock;
    sock.onopen = () => sock.send(JSON.stringify({ type: "start", sessionId: sessionId.current, actorName: "Agent vocal" } satisfies VoiceClientMessage));
    sock.onmessage = onMessage;
    sock.onclose = () => {
      if (ws.current !== sock) return;
      setConn("offline");
      setActivity((a) => (a === "speaking" ? a : "idle"));
      if (alive.current) window.setTimeout(() => { if (ws.current === sock) connect(); }, 3000);
    };
  }, [onMessage]);

  useEffect(() => {
    alive.current = true;
    connect();
    return () => {
      alive.current = false;
      const s = ws.current;
      ws.current = undefined;
      s?.close();
      stopPlayback();
      if (raf.current) cancelAnimationFrame(raf.current);
      try { recorder.current?.stop(); } catch { /* ignore */ }
      stream.current?.getTracks().forEach((t) => t.stop());
      void audioCtx.current?.close().catch(() => undefined);
    };
  }, [connect, stopPlayback]);

  // ── Mic ──
  const ensureMic = useCallback(async (): Promise<MediaStream | undefined> => {
    if (stream.current?.active) return stream.current;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") { setMic("unsupported"); return undefined; }
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: MIC_CONSTRAINTS });
      stream.current = s;
      setMic("granted");
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new Ctx();
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      ctx.createMediaStreamSource(s).connect(an);
      audioCtx.current = ctx;
      analyser.current = an;
      return s;
    } catch (e) {
      setMic((e as DOMException).name === "NotAllowedError" || (e as DOMException).name === "SecurityError" ? "denied" : "unsupported");
      return undefined;
    }
  }, []);

  const meter = useCallback(() => {
    const an = analyser.current;
    if (!an) return;
    const buf = new Uint8Array(an.fftSize);
    const tick = () => {
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) { const x = (v - 128) / 128; sum += x * x; }
      setLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4));
      raf.current = requestAnimationFrame(tick);
    };
    tick();
  }, []);

  // Mic already allowed for this site: open it as soon as the session is ready, so the first words of the first turn
  // are not lost while the microphone warms up. Never prompts (the prompt still comes on the first Space press).
  useEffect(() => {
    if (conn !== "ready" || stream.current?.active) return;
    navigator.permissions?.query({ name: "microphone" as PermissionName })
      .then((p) => { if (p.state === "granted") void ensureMic(); })
      .catch(() => { /* Safari / Firefox: no "microphone" permission query, the mic opens on the first press */ });
  }, [conn, ensureMic]);

  const startTalking = useCallback(async () => {
    try { audioContext(); } catch { /* no Web Audio: the mp3 player is used */ } // unlock on the user gesture (Safari)
    if (pressed.current || conn !== "ready") return;
    pressed.current = true;
    if (tail.current) { // pressed again during the previous release tail: end that recording now, without audio_end
      clearTimeout(tail.current.timer);
      const old = tail.current.rec;
      tail.current = undefined;
      old.onstop = null;
      try { old.stop(); } catch { /* ignore */ }
    }
    stopPlayback();
    const s = await ensureMic();
    // Released while the permission prompt / mic warm-up was pending: do not record a stub.
    if (!s || !pressed.current) { pressed.current = false; return; }
    const mime = REC_MIME.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
    const rec = new MediaRecorder(s, mime ? { mimeType: mime } : undefined);
    recorder.current = rec;
    send({ type: "audio_start", mime: rec.mimeType || mime || "audio/webm" });
    rec.ondataavailable = (e) => { if (e.data.size && ws.current?.readyState === WebSocket.OPEN) ws.current.send(e.data); };
    rec.onstop = () => {
      // The last dataavailable fires before stop, so every chunk has been queued on the socket.
      send({ type: "audio_end" });
    };
    void audioCtx.current?.resume();
    rec.start(100); // a chunk every 100 ms: the STT hears the words while they are spoken
    newTurn({ text: "", at: Date.now(), status: "recording" });
    setActivity("recording");
    setLastError(undefined);
    meter();
  }, [conn, ensureMic, meter, newTurn, send, stopPlayback]);

  const stopTalking = useCallback(() => {
    if (!pressed.current) return;
    pressed.current = false;
    if (raf.current) cancelAnimationFrame(raf.current);
    setLevel(0);
    const rec = recorder.current;
    recorder.current = undefined;
    if (rec && rec.state !== "inactive") {
      releasedAt.current = performance.now(); // "Perçu" counts from the key release, tail included (honest)
      turnReleasedAt.current = releasedAt.current;
      const timer = setTimeout(() => {
        if (tail.current?.rec === rec) tail.current = undefined;
        if (rec.state !== "inactive") rec.stop();
      }, RELEASE_TAIL_MS);
      tail.current = { timer, rec };
      patchTurn(currentTurn.current, (t) => ({ ...t, caller: { ...t.caller, status: "transcribing" } }));
      setActivity("thinking");
    }
  }, [patchTurn]);

  const sendText = useCallback((text: string) => {
    try { audioContext(); } catch { /* no Web Audio */ }
    const v = text.trim();
    if (!v || conn !== "ready") return;
    stopPlayback();
    newTurn({ text: v, at: Date.now(), status: "final", typed: true });
    send({ type: "text", text: v });
    releasedAt.current = performance.now();
    turnReleasedAt.current = releasedAt.current;
    setActivity("thinking");
    setLastError(undefined);
  }, [conn, newTurn, send, stopPlayback]);

  const reset = useCallback(() => {
    stopPlayback();
    send({ type: "reset" });
    currentTurn.current = undefined;
    setTurns([]);
    setActivity("idle");
    setLastError(undefined);
  }, [send, stopPlayback]);

  return {
    conn, activity, mic, providers, turns, level, lastError, deal,
    startTalking, stopTalking, sendText, stopPlayback, reset, reconnect: connect,
  };
}
