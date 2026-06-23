"""키워드 검색(discovery) 계층.

파서(parsers/)가 '개별 상세 URL → JobPost'를 담당한다면, 검색기(searchers/)는
'키워드 → 개별 상세 URL 리스트'를 담당한다. 검색기가 찾아낸 URL은 기존 파서의
can_handle 형태(/wd/, rec_idx=, GI_Read)와 일치하므로, service.collect()가 변경
없이 그대로 처리한다. (레지스트리 SEARCHERS는 PARSERS와 동일하게 service.py에 둔다.)
"""
