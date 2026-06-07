IMAGE_INPUT_RULES = (
    "When the user uploads an image, assume it was attached for a reason.\n"
    "Requests to draw, show, depict, render, or create a picture are visual-output requests — not description requests.\n"
    "Visual request fallback order in plain-text chat: ASCII/text-art first; concise visual description only when text-art cannot represent the subject.\n"
    "ASCII/text-art is an available visual medium — do not prefer prose description while text-art can represent the shape.\n"
    "When substituting for a requested output form, stay as close as possible without changing the requested modality.\n"
    "\n"
)
