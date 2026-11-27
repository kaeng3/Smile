(() => {
    const panel = document.querySelector('#scanner-data');
    const pending = new Map();
    const validCode = code => typeof code === 'string' && /^[0-9A-Z]{6}$/.test(code);
    const date = value => String(value ?? '').replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3');
    const rate = value => value == null || !Number.isFinite(Number(value)) ? '' :
        (Number(value) >= 0 ? '+' : '') + Number(value).toFixed(2) + '%';
    const normalize = value => String(value ?? '').normalize('NFKC').toLowerCase().trim();

    function json(file) {
        if (!pending.has(file)) {
            pending.set(file, fetch('../' + file).then(response => {
                if (!response.ok) throw new Error(String(response.status));
                return response.json();
            }));
        }
        return pending.get(file);
    }

    function add(parent, tag, text, className) {
        const node = document.createElement(tag);
        if (text != null) node.textContent = text;
        if (className) node.className = className;
        parent.append(node);
        return node;
    }

    function select(parent, label, options) {
        const field = add(parent, 'label', label);
        const input = add(field, 'select');
        for (const [value, text] of options) add(input, 'option', text).value = value;
        return input;
    }

    function link(parent, label, url) {
        const anchor = add(parent, 'a', label);
        anchor.href = url;
        return anchor;
    }

    function stock(parent, code, name, label) {
        if (!validCode(code)) return add(parent, 'span', name);
        const url = new URL('history.html', location.href);
        url.search = new URLSearchParams({stock: code, name: name || code});
        return link(parent, label || name || code, url);
    }

    function localAsset(path, folder) {
        if (typeof path !== 'string' || !path.startsWith(folder) || path.includes('\\')) return null;
        const asset = new URL('../' + path, location.href);
        const base = new URL('../' + folder, location.href);
        return asset.origin === base.origin && asset.pathname.startsWith(base.pathname) ? asset : null;
    }

    async function themes() {
        const data = await json('theme_bundles.json');
        const bundles = data.bundles || [];
        add(panel, 'p', [data.generated_at, data.total_events == null ? '' : data.total_events + '건'].filter(Boolean).join(' · '), 'small');
        const controls = add(panel, 'div', null, 'controls');
        const group = select(controls, '분류', [['', '전체'], ...[...new Set(bundles.map(b => b.group))].map(g => [g, g])]);
        const output = add(panel, 'div');
        const maxHeat = Math.max(1, ...bundles.map(b => Number(b.heat) || 0));
        function render() {
            output.replaceChildren();
            const visible = bundles.filter(b => !group.value || b.group === group.value);
            if (!visible.length) add(output, 'p', '등록된 테마꾸러미가 없습니다.', 'small');
            for (const bundle of visible) {
                const row = add(output, 'details', null, 'event');
                add(row, 'summary', [bundle.theme, bundle.group, bundle.reignited ? '재점화' : ''].filter(Boolean).join(' · '));
                const meter = add(row, 'meter');
                meter.max = maxHeat;
                meter.value = Number(bundle.heat) || 0;
                meter.setAttribute('aria-label', bundle.theme + ' 최근 5거래일 강도');
                add(row, 'p', '최근 5거래일 ' + bundle.recent_count + '건 · 누적 ' + bundle.event_count + '건 · ' + bundle.stock_count + '종목');
                stock(add(row, 'p', '대장주 '), bundle.leader_code, bundle.leader);
                add(row, 'p', (data.sessions || []).map(day => date(day) + ((bundle.active_dates || []).includes(day) ? ' ●' : ' ○')).join(' · '), 'small');
                const stocks = add(row, 'ul');
                for (const item of bundle.stocks || []) stock(add(stocks, 'li'), item.code, item.name);
                const timeline = add(row, 'ul');
                for (const item of bundle.events || []) {
                    const entry = add(timeline, 'li', date(item.date) + ' ');
                    stock(entry, item.code, item.name);
                    add(entry, 'span', ' ' + rate(item.rate));
                    add(entry, 'p', item.title || item.summary);
                }
            }
        }
        group.addEventListener('change', render);
        render();
    }

    const strategies = [['v2', '양음양 v2전략', '김일청의_양음양기법_v2전략_'],
        ['podosi', '포도시 차트', '김일청의_포도시차트_'],
        ['b500m', '500억/150억 기준봉', '이동평균선과_500억봉_및_150억봉_분석보고서_']];

    async function scans() {
        const history = await json('scan_history.json');
        const dates = Object.keys(history).sort().reverse().slice(0, 5);
        if (!dates.length) {
            add(panel, 'p', '등록된 스캔 결과가 없습니다.', 'small');
            return;
        }
        const controls = add(panel, 'div', null, 'controls');
        const day = select(controls, '거래일', dates.map(value => [value, date(value)]));
        const strategy = select(controls, '실전 전략', strategies);
        const query = add(add(controls, 'label', '종목명 또는 코드'), 'input');
        query.type = 'search';
        const output = add(panel, 'div');
        function render() {
            output.replaceChildren();
            const results = (history[day.value]?.[strategy.value] || []).filter(item =>
                normalize(item.name + ' ' + item.code).includes(normalize(query.value)));
            const pdf = strategies.find(([key]) => key === strategy.value)[2] + day.value + '.pdf';
            if (history[day.value]?.[strategy.value]?.length) link(output, '전략 PDF', '../' + encodeURIComponent(pdf));
            add(output, 'p', results.length ? results.length + '종목' : '표시할 포착 종목이 없습니다.', 'small');
            for (const item of results) {
                const row = add(output, 'details', null, 'event');
                add(row, 'summary', [item.name, item.code, rate(item.rate), item.pattern].filter(Boolean).join(' · '));
                if (item.comment || item.result_desc) add(row, 'p', item.comment || item.result_desc);
                const chart = localAsset(item.chart, 'charts/');
                if (chart) {
                    const image = add(row, 'img');
                    image.src = chart;
                    image.alt = item.name + ' 차트';
                    image.loading = 'lazy';
                    image.style.maxWidth = '100%';
                }
                stock(row, item.code, item.name, '종목 상세');
            }
        }
        day.addEventListener('change', render);
        strategy.addEventListener('change', render);
        query.addEventListener('input', render);
        render();
    }

    async function section(parent, title, load, render) {
        const body = add(parent, 'section', null, 'event');
        add(body, 'h3', title);
        const status = add(body, 'p', '불러오는 중입니다.', 'small');
        try {
            const data = await load;
            render(body, data);
            status.remove();
        } catch {
            status.textContent = '자료를 불러오지 못했습니다.';
        }
    }

    function rows(parent, items, render) {
        if (!items.length) add(parent, 'p', '등록된 자료가 없습니다.', 'small');
        for (const item of items) render(parent, item);
    }

    async function detail(parent, code, name) {
        add(parent, 'h2', name + ' (' + code + ')');
        const tags = item => [item?.category, ...(item?.subthemes || [])].filter(Boolean);
        const money = value => value == null ? '—' : Math.round(value / 1e8).toLocaleString('ko-KR') + '억 원';
        await Promise.all([
            section(parent, '기업 개요', json('stock_overview.json'), (body, db) => {
                const info = db[code];
                rows(body, info ? [info] : [], (node, item) => {
                    add(node, 'p', [item.market, item.sector === 'nan' ? '' : item.sector, item.marcap ? '시가총액 ' + money(item.marcap) : ''].filter(Boolean).join(' · '));
                    if (item.description) add(node, 'p', item.description);
                });
            }),
            section(parent, '재무 추이', json('stock_financials.json'), (body, db) => {
                rows(body, db[code] || [], (node, item) => add(node, 'p',
                    item.year + '년 · 매출 ' + money(item.revenue) + ' · 영업이익 ' + money(item.operating_profit) + ' · 순이익 ' + money(item.net_income)));
            }),
            section(parent, '연관 테마 및 종목', Promise.all([
                json('stock_detail_themes.json'),
                json('latest_prices.json').catch(() => ({}))
            ]), (body, [db, prices]) => {
                const ownTags = [...new Set(tags(db[code]))];
                if (!ownTags.length) {
                    add(body, 'p', '등록된 테마가 없습니다.', 'small');
                    return;
                }
                const group = select(body, '테마', [['', '전체'], ...ownTags.map(tag => [tag, tag])]);
                const related = add(body, 'ul');
                function render() {
                    related.replaceChildren();
                    const active = group.value ? [group.value] : ownTags;
                    const matches = Object.entries(db).filter(([key, item]) => key !== code && tags(item).some(tag => active.includes(tag)));
                    for (const [key, item] of matches.slice(0, 30)) {
                        const entry = add(related, 'li');
                        stock(entry, key, item.name || prices[key]?.name);
                        const change = rate(prices[key]?.rate);
                        if (change) add(entry, 'span', ' ' + change);
                    }
                    if (!matches.length) add(related, 'li', '연관 종목이 없습니다.');
                }
                group.addEventListener('change', render);
                render();
            }),
            section(parent, 'AI 급등 이슈 요약 이력', json('ai_summary_archive.json'), (body, db) => {
                const list = [...(db[code] || [])].sort((a, b) => String(b.date).localeCompare(String(a.date)));
                rows(body, list, (node, item) => {
                    add(node, 'p', [date(item.date), rate(item.rate)].filter(Boolean).join(' · '), 'small');
                    add(node, 'p', item.summary);
                });
            }),
            section(parent, '과거 종목 뉴스', json('news/' + code + '.json').catch(error => {
                if (error.message === '404') return [];
                throw error;
            }), (body, list) => {
                const months = new Map();
                for (const item of [...list].sort((a, b) => String(b.date).localeCompare(String(a.date)))) {
                    const month = /^(\d{4}-\d{2})/.exec(date(item.date))?.[1] || '날짜 미상';
                    if (!months.has(month)) months.set(month, []);
                    months.get(month).push(item);
                }
                rows(body, [...months], (node, [month, items]) => {
                    const group = add(node, 'details');
                    add(group, 'summary', month + ' (' + items.length + '건)');
                    for (const item of items) {
                        const entry = add(group, 'p', date(item.date) + ' ');
                        const decode = value => {
                            if (!item.enc || !value) return value;
                            try {
                                return new TextDecoder().decode(Uint8Array.from(atob(value), character => character.charCodeAt(0)));
                            } catch {
                                return '';
                            }
                        };
                        const title = decode(item.title) || item.summary;
                        if (item.rate) add(entry, 'span', item.rate + ' ');
                        if (/^https?:\/\//i.test(item.url || '')) link(entry, title, item.url);
                        else add(entry, 'span', title);
                        const source = decode(item.content);
                        if (source && source !== title) {
                            const parsed = new DOMParser().parseFromString(source, 'text/html');
                            add(group, 'p', parsed.body.textContent);
                        }
                    }
                });
            }),
            section(parent, '기본적 분석 보고서', json('reports/fundamental/index.json'), (body, data) => {
                const reports = (Array.isArray(data) ? data : data.reports || []).filter(item => item.code === code);
                rows(body, reports, (node, item) => {
                    const href = localAsset('reports/fundamental/' + encodeURIComponent(item.file), 'reports/fundamental/');
                    if (!href) return;
                    const report = add(node, 'details');
                    add(report, 'summary', [item.date, item.category, item.source || item.name].filter(Boolean).join(' · '));
                    link(add(report, 'p'), '보고서 원본', href);
                    report.addEventListener('toggle', async () => {
                        if (!report.open || report.querySelector('pre')) return;
                        const text = add(report, 'pre', '불러오는 중입니다.', 'scanner-report');
                        try {
                            const response = await fetch(href);
                            if (!response.ok) throw new Error(String(response.status));
                            text.textContent = await response.text();
                        } catch {
                            text.textContent = '보고서 본문을 불러오지 못했습니다.';
                        }
                    });
                });
            })
        ]);
    }

    async function history() {
        const params = new URLSearchParams(location.search);
        const code = params.get('stock');
        const controls = add(panel, 'form', null, 'controls');
        const query = add(add(controls, 'label', '종목명 또는 코드'), 'input');
        query.type = 'search';
        query.required = true;
        add(controls, 'button', '종목 검색').type = 'submit';
        const matches = add(panel, 'ul');
        matches.setAttribute('aria-live', 'polite');
        const content = add(panel, 'div');
        if (validCode(code)) {
            query.value = params.get('name') || code;
            detail(content, code, query.value);
        }
        controls.addEventListener('submit', async event => {
            event.preventDefault();
            const text = normalize(query.value);
            matches.replaceChildren();
            if (!text) return;
            if (validCode(text)) {
                stock(add(matches, 'li'), text);
                return;
            }
            add(matches, 'li', '검색 중입니다.');
            const loaded = await Promise.allSettled([json('latest_prices.json'), json('ai_summary_archive.json'), json('reports/fundamental/index.json')]);
            if (text !== normalize(query.value)) return;
            const names = new Map();
            for (const result of loaded) {
                if (result.status !== 'fulfilled') continue;
                const data = result.value;
                for (const [key, value] of Object.entries(data)) {
                    const first = Array.isArray(value) ? value[0] : value;
                    const name = first?.name;
                    if (validCode(key) && name) names.set(key, name);
                }
                for (const report of data.reports || []) if (validCode(report.code)) names.set(report.code, report.name);
            }
            matches.replaceChildren();
            const found = [...names].filter(([key, name]) => (key + ' ' + normalize(name)).includes(text));
            for (const [key, name] of found.slice(0, 30)) stock(add(matches, 'li'), key, name, name + ' · ' + key);
            if (!found.length) add(matches, 'li', names.size ? '일치하는 종목이 없습니다.' : '종목 목록을 불러오지 못했습니다.');
        });
    }

    const pages = {'themes.html': themes, 'candidates.html': scans, 'history.html': history};
    const run = pages[location.pathname.split('/').pop()];
    if (!panel || !run) return;
    const status = panel.querySelector('[role=status]');
    run().then(() => status.remove(), () => {
        status.textContent = '기존 스캐너 자료를 불러오지 못했습니다.';
    });
})();
