Responses serialized from the real ORBIT schemas (`app.schemas.context.ContextPackage`,
`app.schemas.snapshots.Snapshot`, `model_dump(mode="json")`), with synthetic content only. They pin the
wire format FORGE reads: regenerate them when ORBIT changes its schemas, never edit them by hand to make a
test pass.
