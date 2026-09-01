

## Improvements (approved via Agent Etna simulations)
- The trace shows the agent described its internal processing for POST /api/canvas instead of returning the required success payload with a shape id, so the fix is to specify that endpoint's exact response contract.
  > When handling POST /api/canvas requests to add shapes, do not narrate internal processing. Instead, actually mutate the canvas state and return a JSON response of the form {"success": true, "shapeId": "<generated-id>", "shape": {"type": ..., "color": ..., "x": ..., "y": ..., "width": ..., "height": ...}}. Generate shapeId as a short unique string (e.g. shape_<timestamp>_<rand>). Never respond with 'handled internally' meta-commentary — the HTTP contract requires the created shape's id in the response body. This does not relax any existing gate on execute_terminal_command, HVAC, or vent tools, which still require prior sensor read and policy lookup.
