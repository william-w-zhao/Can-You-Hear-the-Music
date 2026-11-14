import { it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RoomImages from "../src/components/RoomImages";
import { api } from "../src/api";
import { plan } from "./fixtures";

it("crops the selected room row and switches between its six scan views", async () => {
  vi.spyOn(api, "roomImageSheet").mockResolvedValue(
    new Blob(["image"], { type: "image/jpeg" }),
  );
  const close = vi.fn(),
    revoke = vi.fn();
  vi.stubGlobal(
    "createImageBitmap",
    vi.fn().mockResolvedValue({ width: 1270, height: 400, close }),
  );
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = vi.fn(() => "blob:room-images");
      static revokeObjectURL = revoke;
    },
  );
  const view = render(
    <RoomImages sid="office" rid="r2" name="Quiet office" plan={plan} />,
  );
  await screen.findByText("Images from the scan");
  expect(
    screen.getByRole("img", { name: "Quiet office — Wall 1 scan image" }),
  ).toHaveAttribute("viewBox", "470 200 200 200");
  await userEvent.click(screen.getByRole("button", { name: "Show floor" }));
  expect(
    screen.getByRole("img", { name: "Quiet office — Floor scan image" }),
  ).toHaveAttribute("viewBox", "270 200 200 200");
  expect(screen.getByRole("button", { name: "Show floor" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(close).toHaveBeenCalled();
  view.unmount();
  expect(revoke).toHaveBeenCalledWith("blob:room-images");
});

it("labels the illustration honestly when real images are missing and offers retry", async () => {
  const load = vi
    .spyOn(api, "roomImageSheet")
    .mockRejectedValue(new Error("Images not found"));
  render(<RoomImages sid="office" rid="r1" name="Meeting room" plan={plan} />);
  expect(
    await screen.findByText(
      "Scan images unavailable. Showing a room illustration.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("img", { name: /not a scan photograph/ }),
  ).toBeInTheDocument();
  expect(screen.queryByText("Images from the scan")).not.toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "Retry room images" }),
  );
  expect(load).toHaveBeenCalledTimes(2);
});

it("does not show a different room crop when the sheet dimensions do not match the room directory", async () => {
  vi.spyOn(api, "roomImageSheet").mockResolvedValue(new Blob(["image"]));
  vi.stubGlobal(
    "createImageBitmap",
    vi.fn().mockResolvedValue({ width: 1270, height: 600, close: vi.fn() }),
  );
  render(<RoomImages sid="office" rid="r1" name="Meeting room" plan={plan} />);
  await screen.findByText(
    "Scan images unavailable. Showing a room illustration.",
  );
  expect(
    screen.queryByRole("button", { name: "Show floor" }),
  ).not.toBeInTheDocument();
});
