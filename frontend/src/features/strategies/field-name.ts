/**
 * How a field's name reads. In a dialog, among other fields, it is a small bold caption. On the strategy page,
 * where each editor is a section of its own, it reads as the Share and Leverage sections' names do.
 */
export type FieldNameLook = "field" | "section";

export const FIELD_NAME_CLASS: Record<FieldNameLook, string> = {
  field: "text-xs font-semibold leading-5 text-ink-2",
  section: "text-sm leading-5 text-ink-2",
};
