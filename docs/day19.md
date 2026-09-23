Pending
RetrievalEvalCase
    │
    ├── company_id
    ├── question
    ├── as_of
    ├── split
    └── required_block_ids
            ↓
      exact company snapshot
            ↓
   ┌────────┼────────┐
keyword   vector   hybrid
   │         │        │
   └────────┼────────┘
            ↓
      top-k chunks
            ↓
chunk.source_block_ids
            ↓
required block 是否被命中