# 키움 REST 발췌 (원본: kiwoom-rest-api-spec (2).json)
공통 헤더: api-id, authorization: Bearer <token>, cont-yn/next-key(연속조회), Content-Type: application/json;charset=UTF-8
웹소켓: wss://api.kiwoom.com:10000/api/websocket — 접속 후 {'trnm':'LOGIN','token':...} 전송, 서버 PING은 그대로 echo (키움 샘플코드 기준, 명세서엔 미기재)

## au10001 접근토큰 발급  POST https://api.kiwoom.com/oauth2/token
REQ: grant_type(grant_type: client_credentials 입력); appkey(앱키); secretkey(시크릿키)
RES: expires_dt=만료일; token_type=토큰타입; token=접근토큰
EX_REQ: "{    \"grant_type\": \"client_credentials\",    \"appkey\": \"AxserEsdcredca.....\",    \"secretkey\": \"SEefdcwcforehDre2fdvc....\"}"

## ka01300 관심종목 그룹 리스트 조회  POST https://api.kiwoom.com/api/dostk/watchlist
REQ: 
RES: rtcd=처리결과; nofi=그룹갯수; .gcod=그룹코드; .name=그룹명
EX_REQ: "{}"

## ka01301 관심종목 그룹 상세 조회  POST https://api.kiwoom.com/api/dostk/watchlist
REQ: arn_grp_id(그룹SEQ: ka01300 응답 결과의 gcod값을 입력)
RES: rtcd=처리 결과; nofj=종목 갯수; .cod2=종목코드; .bgb=북마크 구분; .bgb_clr=북마크 컬러
EX_REQ: "{    \"arn_grp_id\": \"001\"}"

## ka10099 종목정보 리스트  POST https://api.kiwoom.com/api/dostk/stkinfo
REQ: mrkt_tp(시장구분: 0 : 코스피,
10 : 코스닥,
30 : K-OTC,
50 : 코넥스,
60 : ETN,
70 : 손실제한 ETN,
80 : 금현물)
RES: list=종목리스트; .code=종목코드; .name=종목명; .listCount=상장주식수; .auditInfo=감리구분; .regDay=상장일; .lastPrice=전일종가; .state=종목상태; .marketCode=시장구분코드; .marketName=시장명; .upName=업종명; .upSizeName=회사크기분류; .orderWarning=투자유의종목여부; .companyClassName=회사분류; .nxtEnable=NXT가능여부
EX_REQ: "{    \"mrkt_tp\": \"0\"}"

## ka10095 지정종목 정보요청  POST https://api.kiwoom.com/api/dostk/stkinfo
REQ: stk_cd(종목코드: 거래소별 종목코드<br/>(KRX:039490,NXT:039490_NX,SOR:039490_AL)<br/>여러개의 종목코드 입력시 | 로 구분)
RES: atn_stk_infr=지정종목정보; .stk_cd=종목코드; .stk_nm=종목명; .cur_prc=현재가; .base_pric=기준가; .pred_pre=전일대비; .pred_pre_sig=전일대비기호; .flu_rt=등락율; .trde_qty=거래량; .trde_prica=거래대금; .cntr_qty=체결량; .cntr_str=체결강도; .pred_trde_qty_pre=전일거래량대비; .sel_bid=매도호가; .buy_bid=매수호가; .sel_1th_bid=매도1차호가; .sel_2th_bid=매도2차호가; .sel_3th_bid=매도3차호가; .sel_4th_bid=매도4차호가; .sel_5th_bid=매도5차호가; .buy_1th_bid=매수1차호가; .buy_2th_bid=매수2차호가; .buy_3th_bid=매수3차호가; .buy_4th_bid=매수4차호가; .buy_5th_bid=매수5차호가
EX_REQ: "{    \"stk_cd\": \"005930\"}"

## 0B 주식체결  POST wss://api.kiwoom.com:10000/api/websocket
REQ: trnm(서비스명: REG : 등록 , REMOVE : 해지); grp_no(그룹번호: 여러 종목을 한번에 묶어서 등록/해제 시 사용); refresh(기존등록유지여부: 0: 기존 등록한 그룹에 item/type을 전체 해지 후 등록, 1: 기존 등록한 그룹에 item/type을 추가 및 삭제); data(실시간 등록 리스트: Param List (Array)); - item(실시간 등록 요소: 거래소별 종목코드, 업종코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL)); - type(실시간 항목: TR 코드를 배열로 설정 <br/>
예) "type" : ["0A", "0B", "...."])
RES: return_code=결과코드; return_msg=결과메시지; trnm=서비스명; data=실시간 등록리스트; .type=실시간항목; .name=실시간 항목명; .item=실시간 등록 요소; .values=실시간 값 리스트; ..20=체결시간; ..10=현재가; ..11=전일대비; ..12=등락율; ..13=누적거래량; ..14=누적거래대금; ..25=전일대비기호; ..228=체결강도; ..311=시가총액(억); ..290=장구분; ..567=상한가발생시간; ..1313=순간거래대금
EX_REQ: "{    \"trnm\": \"REG\",    \"grp_no\": \"1\",    \"refresh\": \"1\",    \"data\": [        {            \"item\": [                \"005930\"            ],            \"type\": [                \"0B\"            ]        }    ]}"

## 1h VI발동/해제  POST wss://api.kiwoom.com:10000/api/websocket
REQ: trnm(서비스명: REG : 등록 , REMOVE : 해지); grp_no(그룹번호: 여러 종목을 한번에 묶어서 등록/해제 시 사용); refresh(기존등록유지여부: 0: 기존 등록한 그룹에 item/type을 전체 해지 후 등록, 1: 기존 등록한 그룹에 item/type을 추가 및 삭제); data(실시간 등록 리스트: Param List (Array)); - item(실시간 등록 요소: ※ 현재 TR은 전체 종목이 수신 됩니다. "item": [""] 으로 설정 바랍니다.); - type(실시간 항목: TR 코드를 배열로 설정 <br/>
예) "type" : ["0A", "0B", "...."])
RES: return_code=결과코드; return_msg=결과메시지; trnm=서비스명; data=실시간 등록리스트; .type=실시간항목; .name=실시간 항목명; .item=실시간 등록 요소; .values=실시간 값 리스트; ..9001=종목코드; ..302=종목명; ..13=누적거래량; ..14=누적거래대금; ..9068=VI발동구분; ..9008=KOSPI,KOSDAQ,전체구분; ..9075=장전구분; ..1221=VI발동가격; ..1223=VI발동시각; ..1224=VI해제시각; ..1225=VI적용구분; ..1236=기준가격 정적; ..1237=기준가격 동적; ..1238=괴리율 정적; ..1239=괴리율 동적; ..1489=VI발동가 등락율; ..1490=VI발동횟수
EX_REQ: "{    \"trnm\": \"REG\",    \"grp_no\": \"1\",    \"refresh\": \"1\",    \"data\": [        {            \"item\": [                \"\"            ],            \"type\": [                \"1h\"            ]        }    ]}"
