"""Tests for vector_indexing models.

These tests verify that the ORM models can be imported and that
their basic structure matches the design specification.
"""


class TestCaseVectorModel:
    """Test CaseVector ORM model."""

    def test_import_case_vector(self):
        """CaseVector model can be imported."""
        from app.vector_indexing.models import CaseVector

        assert CaseVector is not None

    def test_tablename_is_case_vectors(self):
        """CaseVector table name is case_vectors."""
        from app.vector_indexing.models import CaseVector

        assert CaseVector.__tablename__ == "case_vectors"

    def test_has_vector_id_pk(self):
        """CaseVector has vector_id as primary key."""
        from app.vector_indexing.models import CaseVector

        pk = CaseVector.__table__.primary_key
        assert pk is not None
        assert pk.columns["vector_id"] is not None

    def test_has_case_id_unique(self):
        """CaseVector case_id has unique constraint."""
        from app.vector_indexing.models import CaseVector

        table = CaseVector.__table__
        # Check unique constraint exists on case_id
        unique_constraints = [c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"]
        case_id_unique = any("case_id" in c.columns for c in unique_constraints)
        assert case_id_unique, "case_id should have unique constraint"

    def test_has_embedding_vector_column(self):
        """CaseVector has embedding_vector column."""
        from app.vector_indexing.models import CaseVector

        assert "embedding_vector" in CaseVector.__table__.columns

    def test_has_filter_columns(self):
        """CaseVector has brand_id, store_id, problem_type, case_status, tags."""
        from app.vector_indexing.models import CaseVector

        required_cols = ["brand_id", "store_id", "problem_type", "case_status", "tags", "case_updated_at"]
        for col in required_cols:
            assert col in CaseVector.__table__.columns, f"Missing column: {col}"

    def test_has_enrichment_fields(self):
        """CaseVector has enrichment_id and enrichment_status."""
        from app.vector_indexing.models import CaseVector

        assert "enrichment_id" in CaseVector.__table__.columns
        assert "enrichment_status" in CaseVector.__table__.columns

    def test_has_embedding_metadata(self):
        """CaseVector has embedding_model_id and embedding_dimension."""
        from app.vector_indexing.models import CaseVector

        assert "embedding_model_id" in CaseVector.__table__.columns
        assert "embedding_dimension" in CaseVector.__table__.columns


class TestVectorIndexJobModel:
    """Test VectorIndexJob ORM model."""

    def test_import_vector_index_job(self):
        """VectorIndexJob model can be imported."""
        from app.vector_indexing.models import VectorIndexJob

        assert VectorIndexJob is not None

    def test_tablename_is_vector_index_jobs(self):
        """VectorIndexJob table name is vector_index_jobs."""
        from app.vector_indexing.models import VectorIndexJob

        assert VectorIndexJob.__tablename__ == "vector_index_jobs"

    def test_has_job_id_pk(self):
        """VectorIndexJob has job_id as primary key."""
        from app.vector_indexing.models import VectorIndexJob

        pk = VectorIndexJob.__table__.primary_key
        assert pk is not None
        assert pk.columns["job_id"] is not None

    def test_has_case_id(self):
        """VectorIndexJob has case_id column."""
        from app.vector_indexing.models import VectorIndexJob

        assert "case_id" in VectorIndexJob.__table__.columns

    def test_has_job_type_and_status(self):
        """VectorIndexJob has job_type and status columns."""
        from app.vector_indexing.models import VectorIndexJob

        assert "job_type" in VectorIndexJob.__table__.columns
        assert "status" in VectorIndexJob.__table__.columns

    def test_has_source_version(self):
        """VectorIndexJob has source_version column."""
        from app.vector_indexing.models import VectorIndexJob

        assert "source_version" in VectorIndexJob.__table__.columns

    def test_has_audit_fields(self):
        """VectorIndexJob has old_vector_id, old_content_hash, new_vector_id for audit."""
        from app.vector_indexing.models import VectorIndexJob

        assert "old_vector_id" in VectorIndexJob.__table__.columns
        assert "old_content_hash" in VectorIndexJob.__table__.columns
        assert "new_vector_id" in VectorIndexJob.__table__.columns

    def test_has_error_fields(self):
        """VectorIndexJob has error_code and error_stage columns."""
        from app.vector_indexing.models import VectorIndexJob

        assert "error_code" in VectorIndexJob.__table__.columns
        assert "error_stage" in VectorIndexJob.__table__.columns

    def test_has_retry_fields(self):
        """VectorIndexJob has retry_count and next_retry_at columns."""
        from app.vector_indexing.models import VectorIndexJob

        assert "retry_count" in VectorIndexJob.__table__.columns
        assert "next_retry_at" in VectorIndexJob.__table__.columns

    def test_has_timestamps(self):
        """VectorIndexJob has started_at and finished_at columns."""
        from app.vector_indexing.models import VectorIndexJob

        assert "started_at" in VectorIndexJob.__table__.columns
        assert "finished_at" in VectorIndexJob.__table__.columns


class TestEnums:
    """Test enum definitions."""

    def test_embedding_job_status_exists(self):
        """EmbeddingJobStatus enum exists."""
        from app.vector_indexing.models import EmbeddingJobStatus

        assert EmbeddingJobStatus is not None

    def test_enrichment_status_exists(self):
        """EnrichmentStatus enum exists."""
        from app.vector_indexing.models import EnrichmentStatus

        assert EnrichmentStatus is not None