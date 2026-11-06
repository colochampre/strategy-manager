import { describe, expect, it } from "vitest";

import { DESCRIPTION_MAX, readDescription } from "@/features/strategies/description-value";

describe("readDescription", () => {
  it("allows 2,000 characters", () => {
    expect(DESCRIPTION_MAX).toBe(2000);
  });

  it.each(["", " ", " \t\r\n ", "\n\n"])("reads %j as blank", (text) => {
    expect(readDescription(text)).toEqual({ blank: true });
  });

  it("does not read a non-breaking space or an ideographic space as blank, as the server keeps them", () => {
    expect(readDescription(" ")).toEqual({ blank: false, tooLong: false, length: 1 });
    expect(readDescription("　")).toEqual({ blank: false, tooLong: false, length: 1 });
  });

  it("counts after trimming only space, tab, CR and LF at both ends, and keeps what is inside", () => {
    expect(readDescription("  \tabc\r\n")).toEqual({ blank: false, tooLong: false, length: 3 });
    expect(readDescription("a\n\tb")).toEqual({ blank: false, tooLong: false, length: 4 });
    expect(readDescription(" ab ")).toEqual({ blank: false, tooLong: false, length: 4 });
  });

  it("accepts exactly 2,000 characters and refuses 2,001", () => {
    expect(readDescription("a".repeat(2000))).toEqual({ blank: false, tooLong: false, length: 2000 });
    expect(readDescription("a".repeat(2001))).toEqual({ blank: false, tooLong: true, length: 2001 });
  });

  it("counts the padding the server trims as nothing", () => {
    expect(readDescription(`  ${"a".repeat(2000)}\n`)).toEqual({ blank: false, tooLong: false, length: 2000 });
  });

  it("counts characters, not UTF-16 units", () => {
    // 1,000 emoji are 2,000 UTF-16 units but 1,000 characters; 2,001 of them are over.
    expect(readDescription("\u{1F600}".repeat(1000))).toEqual({ blank: false, tooLong: false, length: 1000 });
    expect(readDescription("\u{1F600}".repeat(2000))).toEqual({ blank: false, tooLong: false, length: 2000 });
    expect(readDescription("\u{1F600}".repeat(2001))).toEqual({ blank: false, tooLong: true, length: 2001 });
  });
});
