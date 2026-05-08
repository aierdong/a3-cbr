"""案例持久化与过滤查询测试。

测试 CaseRepository 的 CRUD 操作、过滤查询和分页能力。
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import A3Case, StoreInfo
from app.cases.repository import (
    A3CaseRecord,
    A3CaseUpdateData,
    CaseListQueryRepo,
    CaseRepository,
)


def make_utc_now() -> datetime:
    """返回当前 UTC 时间（带时区）。"""
    return datetime.now(timezone.utc)


def create_test_store(
    session: AsyncSession,
    store_id: str | None = None,
    brand_id: str = "brand_001",
    brand_name: str = "测试品牌",
    business_type: str = "火锅",
    store_scale: str = "large",
    franchise_type: str = "加盟",
    city: str = "北京",
    city_tier: str = "一线",
) -> StoreInfo:
    """创建测试门店信息。"""
    if store_id is None:
        store_id = f"store_{uuid.uuid4().hex[:8]}"
    store = StoreInfo(
        store_id=store_id,
        store_name=f"门店_{store_id}",
        brand_id=brand_id,
        brand_name=brand_name,
        business_type=business_type,
        store_scale=store_scale,
        franchise_type=franchise_type,
        city=city,
        city_tier=city_tier,
        updated_at=make_utc_now(),
    )
    session.add(store)
    return store


def create_test_case(
    session: AsyncSession,
    case_id: str | None = None,
    store_id: str = "store_001",
    status: str = "draft",
    created_at: datetime | None = None,
    problem_type: str = "customer_complaint",
    brand_id: str = "brand_001",
    business_type: str = "火锅",
    store_scale: str = "large",
    franchise_type: str = "加盟",
    city: str = "北京",
    city_tier: str = "一线",
) -> A3Case:
    """创建测试案例。"""
    if case_id is None:
        case_id = f"case_{uuid.uuid4().hex[:12]}"
    if created_at is None:
        created_at = make_utc_now()

    # 确保关联的 store 存在
    store = StoreInfo(
        store_id=store_id,
        store_name=f"门店_{store_id}",
        brand_id=brand_id,
        brand_name="测试品牌",
        business_type=business_type,
        store_scale=store_scale,
        franchise_type=franchise_type,
        city=city,
        city_tier=city_tier,
        updated_at=make_utc_now(),
    )
    session.add(store)

    case = A3Case(
        case_id=case_id,
        problem_description="测试问题描述",
        store_id=store_id,
        problem_type=problem_type,
        context='{"scene": "test_scene"}',
        root_cause="测试根因",
        solution_steps='[{"order": 1, "content": "测试步骤"}]',
        outcome='{"result": "improved", "notes": "测试备注"}',
        status=status,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(case)
    return case


class TestCaseRepositoryCreate:
    """测试 CaseRepository.create 方法。"""

    async def test_create_case_success(
        self, db_session: AsyncSession
    ) -> None:
        """创建案例成功并返回记录。"""
        # 准备门店
        create_test_store(db_session, store_id="store_for_create")
        await db_session.flush()

        repo = CaseRepository(db_session)
        record = await repo.create(
            A3CaseRecord(
                problem_description="新问题",
                store_id="store_for_create",
                problem_type="customer_complaint",
                context={"scene": "new_scene"},
                root_cause="新根因",
                solution_steps=[{"order": 1, "content": "步骤一"}],
                outcome={"result": "improved", "notes": "备注"},
            )
        )

        assert record.case_id is not None
        assert record.problem_description == "新问题"
        assert record.store_id == "store_for_create"
        assert record.status == "draft"
        assert record.created_at is not None
        assert record.updated_at is not None
        # store 关联字段
        assert record.store.store_id == "store_for_create"
        assert record.store.store_name == "门店_store_for_create"

    async def test_create_case_without_store_fails(
        self, db_session: AsyncSession
    ) -> None:
        """引用不存在的 store_id 时创建失败。"""
        repo = CaseRepository(db_session)

        with pytest.raises(ValueError) as exc_info:
            await repo.create(
                A3CaseRecord(
                    problem_description="新问题",
                    store_id="nonexistent_store",
                    problem_type="customer_complaint",
                    context={"scene": "scene"},
                    root_cause="根因",
                    solution_steps=[{"order": 1, "content": "步骤"}],
                    outcome={"result": "improved", "notes": "备注"},
                )
            )
        assert "store_id" in str(exc_info.value).lower()

    async def test_create_case_generates_unique_id(
        self, db_session: AsyncSession
    ) -> None:
        """连续创建两个案例时生成不同的 case_id。"""
        create_test_store(db_session, store_id="store_for_unique")
        await db_session.flush()

        repo = CaseRepository(db_session)
        record1 = await repo.create(
            A3CaseRecord(
                problem_description="问题1",
                store_id="store_for_unique",
                problem_type="service_quality",
                context={"scene": "s1"},
                root_cause="r1",
                solution_steps=[{"order": 1, "content": "s1"}],
                outcome={"result": "no_change", "notes": "n1"},
            )
        )
        record2 = await repo.create(
            A3CaseRecord(
                problem_description="问题2",
                store_id="store_for_unique",
                problem_type="service_quality",
                context={"scene": "s2"},
                root_cause="r2",
                solution_steps=[{"order": 1, "content": "s2"}],
                outcome={"result": "unknown", "notes": "n2"},
            )
        )

        assert record1.case_id != record2.case_id

    async def test_create_case_sets_created_at(
        self, db_session: AsyncSession
    ) -> None:
        """创建案例时自动设置 created_at。"""
        create_test_store(db_session, store_id="store_for_time")
        await db_session.flush()

        before = make_utc_now()
        repo = CaseRepository(db_session)
        record = await repo.create(
            A3CaseRecord(
                problem_description="时间测试",
                store_id="store_for_time",
                problem_type="operations",
                context={"scene": "time"},
                root_cause="根因",
                solution_steps=[{"order": 1, "content": "步骤"}],
                outcome={"result": "improved", "notes": "备注"},
            )
        )
        after = make_utc_now()

        assert before <= record.created_at <= after
        assert record.updated_at == record.created_at


class TestCaseRepositoryUpdate:
    """测试 CaseRepository.update 方法。"""

    async def test_update_case_success(
        self, db_session: AsyncSession
    ) -> None:
        """更新案例成功并返回新记录。"""
        create_test_store(db_session, store_id="store_for_update")
        case = create_test_case(db_session, case_id="case_for_update", store_id="store_for_update")
        await db_session.flush()

        repo = CaseRepository(db_session)
        record = await repo.update(
            "case_for_update",
            A3CaseUpdateData(
                problem_description="更新后描述",
                root_cause="更新后根因",
            ),
        )

        assert record is not None
        assert record.problem_description == "更新后描述"
        assert record.root_cause == "更新后根因"
        assert record.case_id == "case_for_update"
        # created_at 不应变化
        assert record.created_at == case.created_at
        # updated_at 应该更新
        assert record.updated_at >= case.created_at

    async def test_update_nonexistent_case_returns_none(
        self, db_session: AsyncSession
    ) -> None:
        """更新不存在的案例返回 None。"""
        create_test_store(db_session, store_id="store_for_update_nonexist")
        await db_session.flush()

        repo = CaseRepository(db_session)
        record = await repo.update(
            "nonexistent_case_id",
            A3CaseUpdateData(problem_description="新描述"),
        )
        assert record is None

    async def test_update_case_with_status_change(
        self, db_session: AsyncSession
    ) -> None:
        """更新案例时修改状态。"""
        create_test_store(db_session, store_id="store_for_status_update")
        create_test_case(
            db_session,
            case_id="case_for_status_update",
            store_id="store_for_status_update",
            status="draft",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        record = await repo.update(
            "case_for_status_update",
            A3CaseUpdateData(status="active"),
        )

        assert record is not None
        assert record.status == "active"

    async def test_update_case_store_id_valid(
        self, db_session: AsyncSession
    ) -> None:
        """更新案例时更换为有效的 store_id。"""
        create_test_store(db_session, store_id="store_update_v1")
        create_test_store(db_session, store_id="store_update_v2")
        create_test_case(
            db_session,
            case_id="case_for_store_update",
            store_id="store_update_v1",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        record = await repo.update(
            "case_for_store_update",
            A3CaseUpdateData(store_id="store_update_v2"),
        )

        assert record is not None
        assert record.store_id == "store_update_v2"
        assert record.store.store_id == "store_update_v2"

    async def test_update_case_store_id_invalid_fails(
        self, db_session: AsyncSession
    ) -> None:
        """更新案例时更换为无效的 store_id 失败。"""
        create_test_store(db_session, store_id="store_for_update_invalid")
        create_test_case(
            db_session,
            case_id="case_for_update_invalid",
            store_id="store_for_update_invalid",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        with pytest.raises(ValueError) as exc_info:
            await repo.update(
                "case_for_update_invalid",
                A3CaseUpdateData(store_id="nonexistent_store_for_update"),
            )
        assert "store_id" in str(exc_info.value).lower()


class TestCaseRepositoryDelete:
    """测试 CaseRepository.delete 方法。"""

    async def test_delete_case_success(
        self, db_session: AsyncSession
    ) -> None:
        """删除存在的案例返回 True。"""
        create_test_store(db_session, store_id="store_for_delete")
        create_test_case(
            db_session,
            case_id="case_for_delete",
            store_id="store_for_delete",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.delete("case_for_delete")

        assert result is True
        # 验证物理删除
        deleted = await db_session.get(A3Case, "case_for_delete")
        assert deleted is None

    async def test_delete_nonexistent_case_returns_false(
        self, db_session: AsyncSession
    ) -> None:
        """删除不存在的案例返回 False。"""
        create_test_store(db_session, store_id="store_for_delete_nonexist")
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.delete("nonexistent_case_for_delete")

        assert result is False

    async def test_delete_case_removes_from_list(
        self, db_session: AsyncSession
    ) -> None:
        """删除案例后列表查询不再返回该案例。"""
        create_test_store(db_session, store_id="store_for_delete_list")
        create_test_case(
            db_session,
            case_id="case_for_delete_list",
            store_id="store_for_delete_list",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        # 先确认存在
        result = await repo.list(
            CaseListQueryRepo(limit=10)
        )
        assert any(item.case_id == "case_for_delete_list" for item in result.items)

        # 删除
        await repo.delete("case_for_delete_list")

        # 再查列表
        result = await repo.list(
            CaseListQueryRepo(limit=10)
        )
        assert all(item.case_id != "case_for_delete_list" for item in result.items)


class TestCaseRepositoryGetById:
    """测试 CaseRepository.get_by_id 方法。"""

    async def test_get_by_id_success(
        self, db_session: AsyncSession
    ) -> None:
        """按 ID 查询存在的案例返回记录。"""
        create_test_store(db_session, store_id="store_for_get")
        create_test_case(
            db_session,
            case_id="case_for_get",
            store_id="store_for_get",
            problem_description="详情测试",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        record = await repo.get_by_id("case_for_get")

        assert record is not None
        assert record.case_id == "case_for_get"
        assert record.problem_description == "详情测试"
        assert record.store.store_id == "store_for_get"

    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession
    ) -> None:
        """按 ID 查询不存在的案例返回 None。"""
        create_test_store(db_session, store_id="store_for_get_nonexist")
        await db_session.flush()

        repo = CaseRepository(db_session)
        record = await repo.get_by_id("nonexistent_case_id")

        assert record is None

    async def test_get_by_id_includes_store_info(
        self, db_session: AsyncSession
    ) -> None:
        """按 ID 查询时包含关联的门店信息。"""
        store_record = create_test_store(
            db_session,
            store_id="store_for_get_info",
            brand_name="测试品牌名称",
            city="上海",
        )
        case = create_test_case(
            db_session,
            case_id="case_for_get_info",
            store_id="store_for_get_info",
            brand_name="测试品牌名称",
            city="上海",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        record = await repo.get_by_id("case_for_get_info")

        assert record is not None
        assert record.store is not None
        assert record.store.brand_name == "测试品牌名称"
        assert record.store.city == "上海"


class TestCaseRepositoryList:
    """测试 CaseRepository.list 方法。"""

    async def test_list_empty_returns_empty_page(
        self, db_session: AsyncSession
    ) -> None:
        """无案例时返回空列表和分页信息。"""
        store = create_test_store(db_session, store_id="store_for_empty_list")
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10)
        )

        assert result.items == []
        assert result.limit == 10
        assert result.has_more is False
        assert result.next_cursor_created_at is None
        assert result.next_cursor_case_id is None
        assert result.sort == "created_at desc, case_id desc"

    async def test_list_returns_cases_with_store_info(
        self, db_session: AsyncSession
    ) -> None:
        """列表查询返回案例及其关联门店信息。"""
        store = create_test_store(
            db_session,
            store_id="store_for_list",
            brand_name="列表品牌",
        )
        case = create_test_case(
            db_session,
            case_id="case_for_list",
            store_id="store_for_list",
            brand_name="列表品牌",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10)
        )

        assert len(result.items) == 1
        assert result.items[0].case_id == "case_for_list"
        assert result.items[0].store.brand_name == "列表品牌"

    async def test_list_filter_by_brand_id(
        self, db_session: AsyncSession
    ) -> None:
        """按 brand_id 过滤列表。"""
        store1 = create_test_store(db_session, store_id="store_brand_1", brand_id="brand_filter_1")
        store2 = create_test_store(db_session, store_id="store_brand_2", brand_id="brand_filter_2")
        case1 = create_test_case(
            db_session,
            case_id="case_brand_1",
            store_id="store_brand_1",
            brand_id="brand_filter_1",
        )
        case2 = create_test_case(
            db_session,
            case_id="case_brand_2",
            store_id="store_brand_2",
            brand_id="brand_filter_2",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10, brand_id="brand_filter_1")
        )

        assert len(result.items) == 1
        assert result.items[0].case_id == "case_brand_1"

    async def test_list_filter_by_store_id(
        self, db_session: AsyncSession
    ) -> None:
        """按 store_id 过滤列表。"""
        store1 = create_test_store(db_session, store_id="store_filter_1")
        store2 = create_test_store(db_session, store_id="store_filter_2")
        case1 = create_test_case(
            db_session,
            case_id="case_store_filter_1",
            store_id="store_filter_1",
        )
        case2 = create_test_case(
            db_session,
            case_id="case_store_filter_2",
            store_id="store_filter_2",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10, store_id="store_filter_1")
        )

        assert len(result.items) == 1
        assert result.items[0].case_id == "case_store_filter_1"

    async def test_list_filter_by_business_type(
        self, db_session: AsyncSession
    ) -> None:
        """按业态过滤列表。"""
        store1 = create_test_store(db_session, store_id="store_biz_1", business_type="火锅")
        store2 = create_test_store(db_session, store_id="store_biz_2", business_type="小吃")
        case1 = create_test_case(
            db_session,
            case_id="case_biz_1",
            store_id="store_biz_1",
            business_type="火锅",
        )
        case2 = create_test_case(
            db_session,
            case_id="case_biz_2",
            store_id="store_biz_2",
            business_type="小吃",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10, business_type="火锅")
        )

        assert len(result.items) == 1
        assert result.items[0].case_id == "case_biz_1"

    async def test_list_filter_by_store_scale(
        self, db_session: AsyncSession
    ) -> None:
        """按门店规模过滤列表。"""
        store1 = create_test_store(db_session, store_id="store_scale_1", store_scale="large")
        store2 = create_test_store(db_session, store_id="store_scale_2", store_scale="small")
        case1 = create_test_case(
            db_session,
            case_id="case_scale_1",
            store_id="store_scale_1",
            store_scale="large",
        )
        case2 = create_test_case(
            db_session,
            case_id="case_scale_2",
            store_id="store_scale_2",
            store_scale="small",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10, store_scale="large")
        )

        assert len(result.items) == 1
        assert result.items[0].case_id == "case_scale_1"

    async def test_list_filter_by_franchise_type(
        self, db_session: AsyncSession
    ) -> None:
        """按加盟类型过滤列表。"""
        store1 = create_test_store(db_session, store_id="store_fran_1", franchise_type="加盟")
        store2 = create_test_store(db_session, store_id="store_fran_2", franchise_type="直营")
        case1 = create_test_case(
            db_session,
            case_id="case_fran_1",
            store_id="store_fran_1",
            franchise_type="加盟",
        )
        case2 = create_test_case(
            db_session,
            case_id="case_fran_2",
            store_id="store_fran_2",
            franchise_type="直营",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10, franchise_type="加盟")
        )

        assert len(result.items) == 1
        assert result.items[0].case_id == "case_fran_1"

    async def test_list_filter_by_city(
        self, db_session: AsyncSession
    ) -> None:
        """按城市过滤列表。"""
        store1 = create_test_store(db_session, store_id="store_city_1", city="北京")
        store2 = create_test_store(db_session, store_id="store_city_2", city="上海")
        case1 = create_test_case(
            db_session,
            case_id="case_city_1",
            store_id="store_city_1",
            city="北京",
        )
        case2 = create_test_case(
            db_session,
            case_id="case_city_2",
            store_id="store_city_2",
            city="上海",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10, city="北京")
        )

        assert len(result.items) == 1
        assert result.items[0].case_id == "case_city_1"

    async def test_list_filter_by_city_tier(
        self, db_session: AsyncSession
    ) -> None:
        """按城市规模过滤列表。"""
        store1 = create_test_store(db_session, store_id="store_tier_1", city_tier="一线")
        store2 = create_test_store(db_session, store_id="store_tier_2", city_tier="二线")
        case1 = create_test_case(
            db_session,
            case_id="case_tier_1",
            store_id="store_tier_1",
            city_tier="一线",
        )
        case2 = create_test_case(
            db_session,
            case_id="case_tier_2",
            store_id="store_tier_2",
            city_tier="二线",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10, city_tier="一线")
        )

        assert len(result.items) == 1
        assert result.items[0].case_id == "case_tier_1"

    async def test_list_filter_by_problem_type(
        self, db_session: AsyncSession
    ) -> None:
        """按问题类型过滤列表。"""
        store = create_test_store(db_session, store_id="store_prob")
        case1 = create_test_case(
            db_session,
            case_id="case_prob_1",
            store_id="store_prob",
            problem_type="customer_complaint",
        )
        case2 = create_test_case(
            db_session,
            case_id="case_prob_2",
            store_id="store_prob",
            problem_type="service_quality",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(
                limit=10, problem_type="customer_complaint"
            )
        )

        assert len(result.items) == 1
        assert result.items[0].case_id == "case_prob_1"

    async def test_list_filter_by_status(
        self, db_session: AsyncSession
    ) -> None:
        """按状态过滤列表。"""
        store = create_test_store(db_session, store_id="store_status")
        case1 = create_test_case(
            db_session,
            case_id="case_status_1",
            store_id="store_status",
            status="draft",
        )
        case2 = create_test_case(
            db_session,
            case_id="case_status_2",
            store_id="store_status",
            status="active",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10, status="active")
        )

        assert len(result.items) == 1
        assert result.items[0].case_id == "case_status_2"

    async def test_list_filter_by_created_time_range(
        self, db_session: AsyncSession
    ) -> None:
        """按创建时间范围过滤列表。"""
        base_time = make_utc_now()
        store = create_test_store(db_session, store_id="store_time_range")
        case_old = create_test_case(
            db_session,
            case_id="case_time_old",
            store_id="store_time_range",
            created_at=base_time - timedelta(days=10),
        )
        case_mid = create_test_case(
            db_session,
            case_id="case_time_mid",
            store_id="store_time_range",
            created_at=base_time - timedelta(days=5),
        )
        case_new = create_test_case(
            db_session,
            case_id="case_time_new",
            store_id="store_time_range",
            created_at=base_time,
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        # 查询 base_time - 7 天到 base_time + 1 天
        result = await repo.list(
            CaseListQueryRepo(
                limit=10,
                created_after=base_time - timedelta(days=7),
                created_before=base_time + timedelta(days=1),
            )
        )

        case_ids = [item.case_id for item in result.items]
        assert "case_time_mid" in case_ids
        assert "case_time_new" in case_ids
        assert "case_time_old" not in case_ids

    async def test_list_excludes_archived_by_default(
        self, db_session: AsyncSession
    ) -> None:
        """默认不包含归档状态的案例。"""
        store = create_test_store(db_session, store_id="store_no_archive")
        case_draft = create_test_case(
            db_session,
            case_id="case_no_archive_draft",
            store_id="store_no_archive",
            status="draft",
        )
        case_archived = create_test_case(
            db_session,
            case_id="case_no_archive_archived",
            store_id="store_no_archive",
            status="archived",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10)
        )

        case_ids = [item.case_id for item in result.items]
        assert "case_no_archive_draft" in case_ids
        assert "case_no_archive_archived" not in case_ids

    async def test_list_include_archived(
        self, db_session: AsyncSession
    ) -> None:
        """include_archived=True 时包含归档案例。"""
        store = create_test_store(db_session, store_id="store_with_archive")
        case_draft = create_test_case(
            db_session,
            case_id="case_with_archive_draft",
            store_id="store_with_archive",
            status="draft",
        )
        case_archived = create_test_case(
            db_session,
            case_id="case_with_archive_archived",
            store_id="store_with_archive",
            status="archived",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(
                limit=10, include_archived=True
            )
        )

        case_ids = [item.case_id for item in result.items]
        assert "case_with_archive_draft" in case_ids
        assert "case_with_archive_archived" in case_ids

    async def test_list_stable_sorting(
        self, db_session: AsyncSession
    ) -> None:
        """列表使用稳定排序 created_at desc, case_id desc。"""
        base_time = make_utc_now()
        store = create_test_store(db_session, store_id="store_sort")
        case1 = create_test_case(
            db_session,
            case_id="case_sort_a",
            store_id="store_sort",
            created_at=base_time - timedelta(hours=1),
        )
        case2 = create_test_case(
            db_session,
            case_id="case_sort_b",
            store_id="store_sort",
            created_at=base_time - timedelta(hours=1),
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10)
        )

        # 按 created_at desc, case_id desc 排序
        assert len(result.items) == 2
        # case_sort_b 应该在 case_sort_a 前面（case_id 字典序更小）
        assert result.items[0].case_id == "case_sort_b"
        assert result.items[1].case_id == "case_sort_a"

    async def test_list_keyset_pagination(
        self, db_session: AsyncSession
    ) -> None:
        """keyset 分页正确工作。"""
        base_time = make_utc_now()
        store = create_test_store(db_session, store_id="store_page")
        cases = []
        for i in range(5):
            case = create_test_case(
                db_session,
                case_id=f"case_page_{i}",
                store_id="store_page",
                created_at=base_time - timedelta(hours=i),
            )
            cases.append(case)
        await db_session.flush()

        repo = CaseRepository(db_session)
        # 第一页
        page1 = await repo.list(
            CaseListQueryRepo(limit=2)
        )

        assert len(page1.items) == 2
        assert page1.has_more is True
        assert page1.next_cursor_created_at is not None
        assert page1.next_cursor_case_id is not None

        # 第二页
        page2 = await repo.list(
            CaseListQueryRepo(
                limit=2,
                cursor_created_at=page1.next_cursor_created_at,
                cursor_case_id=page1.next_cursor_case_id,
            )
        )

        assert len(page2.items) == 2
        # 不应包含第一页的案例
        page1_ids = [item.case_id for item in page1.items]
        page2_ids = [item.case_id for item in page2.items]
        assert set(page1_ids) & set(page2_ids) == set()

    async def test_list_last_page_has_no_next_cursor(
        self, db_session: AsyncSession
    ) -> None:
        """末页没有下一页游标。"""
        store = create_test_store(db_session, store_id="store_last_page")
        case = create_test_case(
            db_session,
            case_id="case_last_page",
            store_id="store_last_page",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(limit=10)
        )

        assert len(result.items) == 1
        assert result.has_more is False
        assert result.next_cursor_created_at is None
        assert result.next_cursor_case_id is None

    async def test_list_multiple_filters(
        self, db_session: AsyncSession
    ) -> None:
        """同时使用多个过滤条件。"""
        store1 = create_test_store(
            db_session,
            store_id="store_multi_1",
            brand_id="brand_multi",
            city="北京",
            city_tier="一线",
        )
        store2 = create_test_store(
            db_session,
            store_id="store_multi_2",
            brand_id="brand_multi",
            city="上海",
            city_tier="二线",
        )
        case1 = create_test_case(
            db_session,
            case_id="case_multi_1",
            store_id="store_multi_1",
            brand_id="brand_multi",
            city="北京",
            city_tier="一线",
        )
        case2 = create_test_case(
            db_session,
            case_id="case_multi_2",
            store_id="store_multi_2",
            brand_id="brand_multi",
            city="上海",
            city_tier="二线",
        )
        await db_session.flush()

        repo = CaseRepository(db_session)
        result = await repo.list(
            CaseListQueryRepo(
                limit=10,
                brand_id="brand_multi",
                city="北京",
            )
        )

        assert len(result.items) == 1
        assert result.items[0].case_id == "case_multi_1"
