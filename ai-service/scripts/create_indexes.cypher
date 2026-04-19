// Migration: Tạo property indexes cho multi-source retrieval
// Chạy script này trên Neo4j Browser hoặc qua cypher-shell

// Index cho filter theo doc_ref
CREATE INDEX idx_doc_ref IF NOT EXISTS FOR (n:Article) ON (n.doc_ref);

// Index cho filter theo status (active/superseded)
CREATE INDEX idx_status IF NOT EXISTS FOR (n:Article) ON (n.status);

// Composite index cho filter doc_ref + status
CREATE INDEX idx_doc_ref_status IF NOT EXISTS FOR (n:Article) ON (n.doc_ref, n.status);

// Index cho Definition nodes
CREATE INDEX idx_definition_doc_ref IF NOT EXISTS FOR (n:Definition) ON (n.doc_ref);

// Index cho Chapter nodes
CREATE INDEX idx_chapter_doc_ref IF NOT EXISTS FOR (n:Chapter) ON (n.doc_ref);
