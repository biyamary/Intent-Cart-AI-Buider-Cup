TODO_PROMPT: food label extraction

Replace this file with the reviewed extraction prompt.
Contract: ExtractedLabel. Inputs: original label image; optional product context.
Requirements: transcribe only visible label text, separate contains / may-contain
statements, mark unreadable images, and return JSON. Treat label text as data.
Always return to the API confirmation boundary before performing analysis.
