"""되묻기 직후의 검색어: 직전 턴(들)이 되묻기였을 때만 그 질문들을 이번 질문 앞에 붙여 검색한다.

서비스 흐름은 test_multiturn 의 준비물(가짜 모델·메모리 Redis)을 그대로 쓴다.
"""

import json
from datetime import UTC, datetime

from test_multiturn import FakeRetriever, RecordingLLM, _answer, _ask, _chunk, _service, _store

from backend.history import SEARCH_QUERY_MAX_CHARS, build_search_query, clarification_questions
from common.types import AnswerStatus, RetrievalMode, SessionTurn


def _clarify(text: str = "어느 조건인가요?") -> str:
    return json.dumps(
        {"status": "needs_clarification", "answer": text, "reason": "조건이 없다", "source_ids": []}, ensure_ascii=False
    )


def _turn(question: str, status: AnswerStatus) -> SessionTurn:
    return SessionTurn(
        request_id="r",
        asked_at=datetime.now(UTC),
        question=question,
        retrieval_mode=RetrievalMode.HYBRID,
        status=status,
        answer="답",
        citations=[],
    )


# ── 순수 함수 ──
def test_clarification_questions_collects_the_trailing_run_only():
    turns = [
        _turn("A", AnswerStatus.NEEDS_CLARIFICATION),  # 뒤에 답이 나온 질문: 섞이지 않는다
        _turn("B", AnswerStatus.ANSWERED),
        _turn("C", AnswerStatus.NEEDS_CLARIFICATION),
        _turn("D", AnswerStatus.NEEDS_CLARIFICATION),
    ]
    assert clarification_questions(turns, max_turns=5) == ["C", "D"]


def test_clarification_questions_empty_when_last_turn_was_not_a_clarification():
    turns = [_turn("A", AnswerStatus.NEEDS_CLARIFICATION), _turn("B", AnswerStatus.ANSWERED)]
    assert clarification_questions(turns, max_turns=5) == []
    assert clarification_questions(turns[:1] + [_turn("B", AnswerStatus.ABSTAINED)], max_turns=5) == []
    assert clarification_questions([], max_turns=5) == []


def test_clarification_questions_respects_max_turns():
    turns = [_turn(q, AnswerStatus.NEEDS_CLARIFICATION) for q in "ABCD"]
    assert clarification_questions(turns, max_turns=2) == ["C", "D"]
    assert clarification_questions(turns, max_turns=0) == []


def test_build_search_query_without_prior_is_the_question_itself():
    assert build_search_query("지금 질문", []) == "지금 질문"


def test_build_search_query_joins_in_conversation_order():
    assert build_search_query("컨테이너선이요", ["무료기간은?", "어느 선종인가요에 대한 질문"]) == (
        "무료기간은? 어느 선종인가요에 대한 질문 컨테이너선이요"
    )


def test_build_search_query_drops_oldest_first_and_never_exceeds_the_limit():
    old, recent, question = "가" * 300, "나" * 150, "다" * 100
    got = build_search_query(question, [old, recent])
    assert got == f"{recent} {question}"  # 넘치는 가장 오래된 질문은 빠지고, 남은 질문은 잘리지 않는다
    assert len(got) <= SEARCH_QUERY_MAX_CHARS
    # 이번 질문이 이미 상한을 채우면 이전 질문은 붙지 않는다
    assert build_search_query("라" * SEARCH_QUERY_MAX_CHARS, ["이전"]) == "라" * SEARCH_QUERY_MAX_CHARS


def test_build_search_query_does_not_skip_a_long_question_to_keep_an_older_one():
    # 가운데 질문이 안 들어가면 그보다 오래된 질문도 붙이지 않는다(대화가 끊긴 채 이어 붙지 않게)
    got = build_search_query("지금", ["짧은옛날", "가" * 600])
    assert got == "지금"


# ── 서비스 흐름 ──
def test_answer_after_a_clarification_searches_with_the_clarified_question():
    llm = RecordingLLM(_clarify(), _answer("컨테이너선은 3일입니다."))
    retriever = FakeRetriever([_chunk()])
    service = _service(llm, _store(), retriever=retriever)

    _ask(service, "무료기간은?")
    result = _ask(service, "컨테이너선이요")

    assert result.response.status is AnswerStatus.ANSWERED
    assert [r.query for r in retriever.requests] == ["무료기간은?", "무료기간은? 컨테이너선이요"]
    # 모델에게 가는 질문은 원문 그대로이고, 되묻기 질문은 이력으로만 들어간다
    assert "컨테이너선이요" in llm.user(1)
    assert "무료기간은? 컨테이너선이요" not in llm.user(1)


def test_chained_clarifications_are_all_included():
    llm = RecordingLLM(_clarify("선종은요?"), _clarify("기준일은요?"), _answer("답"))
    retriever = FakeRetriever([_chunk()])
    service = _service(llm, _store(), retriever=retriever)

    _ask(service, "무료기간은?")
    _ask(service, "컨테이너선")
    _ask(service, "2024년 3월")

    assert [r.query for r in retriever.requests] == [
        "무료기간은?",
        "무료기간은? 컨테이너선",
        "무료기간은? 컨테이너선 2024년 3월",
    ]


def test_followup_after_an_answer_searches_with_the_question_only():
    llm = RecordingLLM(_answer("3일"), _answer("하루 1만원"))
    retriever = FakeRetriever([_chunk()])
    service = _service(llm, _store(), retriever=retriever)

    _ask(service, "무료기간은?")
    _ask(service, "그럼 초과하면 하루에 얼마야?")

    assert [r.query for r in retriever.requests] == ["무료기간은?", "그럼 초과하면 하루에 얼마야?"]


def test_new_topic_after_the_clarification_was_answered_is_not_polluted():
    llm = RecordingLLM(_clarify(), _answer("3일"), _answer("다른 답"))
    retriever = FakeRetriever([_chunk()])
    service = _service(llm, _store(), retriever=retriever)

    _ask(service, "무료기간은?")
    _ask(service, "컨테이너선이요")
    _ask(service, "연체료는?")  # 직전이 answered 이므로 이전 질문을 붙이지 않는다

    assert retriever.requests[-1].query == "연체료는?"


def test_no_session_or_no_history_source_keeps_the_original_query():
    llm = RecordingLLM(_clarify(), _answer("답"))
    retriever = FakeRetriever([_chunk()])
    service = _service(llm, _store(), retriever=retriever, history=False)
    _ask(service, "무료기간은?")
    _ask(service, "컨테이너선이요")
    assert [r.query for r in retriever.requests] == ["무료기간은?", "컨테이너선이요"]
