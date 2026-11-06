// 설정값은 이 파일 한 곳에 모은다.

/**
 * 질문 최대 글자 수. 계약(QueryRequest.question 의 maxLength)과 같다.
 * 브라우저 maxLength 는 UTF-16 단위라 이모지를 2자로 센다. 서버(Python len)보다 엄격한 쪽이라 길이 초과 422 를 받지 않는다
 */
export const MAX_QUESTION_LENGTH = 500;
