/** What the control draws and tells its container. Presentational: it holds no state and sends nothing. */
export interface ShareSliderProps {
  /** The id of the field, so the visible label can point at it. */
  fieldId: string;
  /** The id of the visible label, which names the track as well. */
  labelId: string;
  /** The field's text exactly as typed. */
  text: string;
  /** The handle's whole step, 1 to 100. */
  handle: number;
  /** The share the text reads as, in canonical form, or `null` when the text is not a value. */
  value: string | null;
  disabled: boolean;
  invalid: boolean;
  /** The id of the validation text that explains `invalid`, when one shows. */
  describedBy?: string;
  onText: (text: string) => void;
  onHandle: (step: number) => void;
  onStop: (stop: number) => void;
}

export function ShareSlider({ fieldId, text, onText }: ShareSliderProps) {
  return (
    <div>
      <span aria-hidden="true">%</span>
      <input id={fieldId} type="text" size={12} value={text} onChange={(event) => onText(event.target.value)} />
    </div>
  );
}
