/**
 * Plays one agent audio segment as it arrives. MediaSource when the browser can stream that mime (mp3 in Chromium/Firefox),
 * so the first sentence plays before the turn is finished; otherwise the chunks are collected and played as one Blob.
 */
export interface PlayerCallbacks {
  onPlaying: () => void; // the segment starts playing (often the acknowledgement)
  onEnded: () => void;
  onUsefulPlaying?: () => void; // the real answer starts playing (after markUseful(); latency diagnosis)
}

/**
 * Where the useful answer starts in a segment: the server sends agent_audio_mark before the first useful bytes.
 * markAt(n) = the useful audio starts with chunk n; appended(i, bufferedEnd) is called before chunk i is appended,
 * with the media time buffered so far; `time` is then the media time where the useful audio starts.
 */
export class UsefulMark {
  chunk: number | undefined;
  time: number | undefined;
  markAt(chunkIndex: number) { if (this.chunk === undefined) this.chunk = chunkIndex; }
  appended(chunkIndex: number, bufferedEnd: number) {
    if (this.chunk === chunkIndex && this.time === undefined) this.time = bufferedEnd;
  }
  /** The playhead reached the useful audio. */
  reached(currentTime: number) { return this.time !== undefined && currentTime >= this.time - 0.005; }
}

/** The browser plays the seller faster than ElevenLabs' maximum (1.2), pitch kept: « beaucoup trop lent » (mar. 17:00).
 *  Tunable without a rebuild: in the browser console, localStorage.voiceRate = "1.25" then reload (1 = off). */
const PLAYBACK_RATE = (() => {
  try {
    const v = Number(localStorage.getItem("voiceRate"));
    return v >= 0.8 && v <= 2 ? v : 1.15;
  } catch { return 1.15; }
})();

export class SegmentPlayer {
  private el: HTMLAudioElement | undefined;
  private url: string | undefined;
  private ms: MediaSource | undefined;
  private sb: SourceBuffer | undefined;
  private queue: ArrayBuffer[] = [];
  private chunks: ArrayBuffer[] = [];
  private ended = false;
  private stopped = false;
  private playingFired = false;
  private mark = new UsefulMark();
  private appended = 0;
  private usefulFired = false;
  private raf = 0;

  constructor(private mime: string, private cb: PlayerCallbacks) {
    const canStream = typeof MediaSource !== "undefined" && MediaSource.isTypeSupported(mime);
    if (!canStream) return;
    const ms = new MediaSource();
    this.ms = ms;
    this.open(URL.createObjectURL(ms));
    ms.addEventListener("sourceopen", () => {
      if (this.stopped) return;
      try {
        this.sb = ms.addSourceBuffer(this.mime);
        this.sb.addEventListener("updateend", () => this.pump());
        this.pump();
      } catch {
        this.ms = undefined; // fall back to Blob
        this.release();
        if (this.ended) this.end();
      }
    }, { once: true });
  }

  private open(url: string) {
    this.url = url;
    const el = new Audio(url);
    el.preservesPitch = true; // faster, same voice (no chipmunk effect)
    el.playbackRate = PLAYBACK_RATE;
    el.onloadedmetadata = () => { el.playbackRate = PLAYBACK_RATE; }; // some browsers reset it on load
    this.el = el;
    el.onplaying = () => {
      if (!this.playingFired) { this.playingFired = true; this.cb.onPlaying(); }
      this.watchUseful();
    };
    el.onended = () => this.finish();
    el.onerror = () => this.finish();
    el.play().catch(() => { /* autoplay blocked or aborted: onerror/stop handle it */ });
  }

  private pump() {
    const sb = this.sb;
    if (!sb || sb.updating || this.stopped) return;
    const next = this.queue.shift();
    if (next) {
      this.mark.appended(this.appended++, sb.buffered.length ? sb.buffered.end(sb.buffered.length - 1) : 0);
      try { sb.appendBuffer(next); } catch { /* quota / closed */ }
      this.watchUseful();
      return;
    }
    if (this.ended && this.ms?.readyState === "open") {
      try { this.ms.endOfStream(); } catch { /* ignore */ }
    }
  }

  /** The next pushed chunk starts the real answer (agent_audio_mark). */
  markUseful() {
    this.mark.markAt(this.chunks.length);
    if (!this.ms) this.mark.time = this.mark.chunk === 0 ? 0 : undefined; // Blob: only "useful from the start" is known
    this.watchUseful();
  }

  /** Fires onUsefulPlaying once the playhead reaches the useful audio (polled per frame while playing). */
  private watchUseful() {
    if (this.usefulFired || this.raf || !this.cb.onUsefulPlaying || this.mark.chunk === undefined) return;
    const tick = () => {
      this.raf = 0;
      const el = this.el;
      if (this.stopped || this.usefulFired || !el) return;
      if (!el.paused && this.playingFired && this.mark.reached(el.currentTime)) {
        this.usefulFired = true;
        this.cb.onUsefulPlaying?.();
        return;
      }
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  push(buf: ArrayBuffer) {
    if (this.stopped) return;
    this.chunks.push(buf);
    if (this.ms) { this.queue.push(buf); this.pump(); }
  }

  end() {
    if (this.stopped) return;
    this.ended = true;
    if (this.ms) { this.pump(); return; } // streaming (or sourceopen pending): pump() ends the stream once drained
    // Blob fallback (or MediaSource refused the mime)
    this.release();
    if (!this.chunks.length) { this.finish(); return; }
    this.ms = undefined;
    this.open(URL.createObjectURL(new Blob(this.chunks, { type: this.mime })));
  }

  stop() {
    if (this.stopped) return;
    this.el?.pause();
    this.finish();
  }

  private finish() {
    if (this.stopped) return;
    this.stopped = true;
    this.release();
    this.cb.onEnded();
  }

  private release() {
    if (this.raf) { cancelAnimationFrame(this.raf); this.raf = 0; }
    if (this.el) { this.el.onended = this.el.onerror = this.el.onplaying = null; this.el.pause(); }
    if (this.url) URL.revokeObjectURL(this.url);
    this.el = undefined;
    this.url = undefined;
  }
}
