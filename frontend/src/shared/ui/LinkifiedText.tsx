import { linkify } from "@/shared/lib/linkify";

/** Plain text in which http and https URLs are links. Nothing else in the text is interpreted. */
export function LinkifiedText({ text }: { text: string }) {
  return (
    <>
      {linkify(text).map((segment, index) =>
        segment.kind === "link" ? (
          <a
            key={index}
            href={segment.text}
            target="_blank"
            rel="noopener noreferrer"
            className="text-gain underline underline-offset-2 hover:text-gain-bright"
          >
            {segment.text}
          </a>
        ) : (
          segment.text
        ),
      )}
    </>
  );
}
