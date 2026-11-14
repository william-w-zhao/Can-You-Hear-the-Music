import { it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Listen from "../src/components/Listen";
import { api } from "../src/api";
import { details, second } from "./fixtures";

function fakeAudio() {
  const sources: any[] = [],
    gains: any[] = [];
  const node = () => ({
    connect: vi.fn(function (this: any, next: any) {
      return next;
    }),
    disconnect: vi.fn(),
  });
  const context = {
    state: "running",
    sampleRate: 8000,
    destination: node(),
    resume: vi.fn(async () => {}),
    close: vi.fn(async () => {}),
    createBuffer: (channels: number, length: number, sampleRate: number) => {
      const data = Array.from(
        { length: channels },
        () => new Float32Array(length),
      );
      return {
        duration: length / sampleRate,
        getChannelData: (i: number) => data[i],
      };
    },
    createBufferSource: () => {
      const source = { ...node(), buffer: null, start: vi.fn(), stop: vi.fn() };
      sources.push(source);
      return source;
    },
    createConvolver: () => ({ ...node(), normalize: true, buffer: null }),
    createGain: () => {
      const gain = { ...node(), gain: { value: 1 } };
      gains.push(gain);
      return gain;
    },
    createDynamicsCompressor: node,
    decodeAudioData: vi.fn(),
  };
  const Constructor = vi.fn(function () {
    return context;
  });
  vi.stubGlobal("AudioContext", Constructor);
  return { context, Constructor, sources, gains };
}
const choices = [
  { label: "Selected room", room: details.room },
  { label: "Comparison room", room: second.room },
];

it("starts only on user action, reuses the same clap and gain, and cleans up on stop/unmount", async () => {
  const audio = fakeAudio();
  const view = render(<Listen choices={choices} voiceUrl={null} />);
  expect(audio.Constructor).not.toHaveBeenCalled();
  expect(
    screen
      .getAllByRole("button", { name: "▶ Voice" })
      .every((b) => (b as HTMLButtonElement).disabled),
  ).toBe(true);
  await userEvent.click(screen.getAllByRole("button", { name: "▶ Clap" })[0]);
  await waitFor(() => expect(audio.sources[0].start).toHaveBeenCalled());
  await userEvent.click(screen.getAllByRole("button", { name: "▶ Clap" })[1]);
  await waitFor(() => expect(audio.sources[1].start).toHaveBeenCalled());
  expect(audio.sources[0].buffer).toBe(audio.sources[1].buffer);
  expect(audio.gains.map((g) => g.gain.value)).toEqual([0.35, 0.35]);
  expect(audio.sources[0].stop).toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Stop audio" }));
  expect(audio.sources[1].disconnect).toHaveBeenCalled();
  view.unmount();
  expect(audio.context.close).toHaveBeenCalled();
});

it("reports a missing voice file and keeps clap playback available", async () => {
  const audio = fakeAudio();
  vi.spyOn(api, "voice").mockRejectedValue(new Error("Voice clip not found"));
  render(<Listen choices={choices} voiceUrl="/audio/voice.wav" />);
  await userEvent.click(screen.getAllByRole("button", { name: "▶ Voice" })[0]);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Voice clip not found",
  );
  expect(audio.sources).toHaveLength(0);
  expect(
    screen.getAllByRole("button", { name: "▶ Clap" })[0],
  ).not.toBeDisabled();
});
