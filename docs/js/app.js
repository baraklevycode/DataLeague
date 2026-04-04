/**
 * Main Alpine.js application — routing, global state, and component definitions.
 */

// -- Helpers --

function posLabel(pos) {
    return { 1: 'שוער', 2: 'מגן', 3: 'קשר', 4: 'חלוץ' }[pos] || '?';
}

function posClass(pos) {
    return {
        1: 'bg-yellow-100 text-yellow-800',
        2: 'bg-blue-100 text-blue-800',
        3: 'bg-green-100 text-green-800',
        4: 'bg-red-100 text-red-800',
    }[pos] || 'bg-gray-100';
}

function formatPrice(price) {
    if (!price) return '-';
    if (price >= 1000000) return (price / 1000000).toFixed(1) + 'M';
    if (price >= 1000) return (price / 1000).toFixed(0) + 'K';
    return price.toString();
}

function powerRankedTeams() {
    return [...Alpine.store('data').teams].sort((a, b) => (a.formRank || 99) - (b.formRank || 99));
}

function getPenaltyTaker(teamId, rank) {
    const r = rank || 1;
    const players = Alpine.store('data').players.filter(p => p.teamId === teamId && p.penaltyRank === r);
    return players.length ? players[0].name : null;
}

// -- Main App --

function app() {
    return {
        page: 'players',
        pageParam: null,
        loading: true,
        error: null,
        isDark: localStorage.getItem('darkMode') !== 'false',
        menuOpen: false,

        async init() {
            if (this.isDark) document.documentElement.classList.add('dark');

            this.parseHash();
            window.addEventListener('hashchange', () => this.parseHash());

            try {
                await Alpine.store('data').load();
                this.loading = false;
            } catch (err) {
                this.loading = false;
                this.error = 'שגיאה בטעינת הנתונים: ' + err.message;
            }
        },

        toggleDark() {
            this.isDark = !this.isDark;
            document.documentElement.classList.toggle('dark', this.isDark);
            localStorage.setItem('darkMode', this.isDark);
        },

        parseHash() {
            const hash = window.location.hash || '#/players';
            const parts = hash.replace('#/', '').split('/');

            if (parts[0] === 'players' && parts[1]) {
                this.page = 'playerDetail';
                this.pageParam = parts[1];
            } else if (parts[0] === 'teams' && parts[1]) {
                this.page = 'teamDetail';
                this.pageParam = parts[1];
            } else {
                this.page = parts[0] || 'players';
                this.pageParam = null;
            }
        }
    };
}

// -- Player Table Component --

function playerTable() {
    return {
        search: '',
        posFilter: '',
        teamFilter: '',
        maxPriceM: null,
        roundMode: 'season',
        selectedRounds: [],
        sortDesc: true,
        currentPage: 1,
        pageSize: 50,
        sortBy: 'fantasyPoints',
        posLabel, posClass, formatPrice,

        get availableRounds() {
            const rounds = Object.keys(Alpine.store('data').rounds || {}).map(Number).sort((a, b) => a - b);
            return rounds;
        },

        initFilters() {
            this.$watch('search', () => this.currentPage = 1);
            this.$watch('posFilter', () => this.currentPage = 1);
            this.$watch('teamFilter', () => this.currentPage = 1);
            this.$watch('maxPriceM', () => this.currentPage = 1);
            this.$watch('sortBy', () => this.currentPage = 1);
        },

        toggleRound(r) {
            const idx = this.selectedRounds.indexOf(r);
            if (idx >= 0) this.selectedRounds.splice(idx, 1);
            else this.selectedRounds.push(r);
            this.roundMode = 'pick';
        },

        selectLastN(n) {
            const rounds = this.availableRounds;
            this.selectedRounds = rounds.slice(-n);
            this.roundMode = 'pick';
        },

        toggleSort(col) {
            if (this.sortBy === col) {
                this.sortDesc = !this.sortDesc;
            } else {
                this.sortBy = col;
                this.sortDesc = true;
            }
        },

        getStat(player, stat) {
            if (this.roundMode === 'pick' && this.selectedRounds.length > 0) {
                return this.getMultiRoundStat(player, stat);
            }
            const s5 = player.sport5;
            const fc = player.footballCoIl;
            switch (stat) {
                case 'fantasyPoints': return s5 ? s5.totalPoints : 0;
                case 'ppm': return player.ppm > 0 ? player.ppm.toFixed(1) : '-';
                case 'goals': return s5 ? s5.goals : 0;
                case 'assists': return s5 ? s5.assists : 0;
                case 'xG': return fc ? fc.expectedGoals.toFixed(2) : '-';
                case 'xA': return player.xA > 0 ? player.xA.toFixed(2) : '-';
                case 'xGI': return player.xGI > 0 ? player.xGI.toFixed(2) : '-';
                case 'shotAttempts': return fc ? fc.shotAttempts : (s5 ? '-' : '-');
                case 'minutes': return s5 ? s5.minutesPlayed : 0;
                case 'cleanSheets': return s5 ? s5.cleanSheets : 0;
                case 'subIn': return s5 ? s5.substituteIn : 0;
                case 'subOut': return s5 ? s5.substituteOut : 0;
                case 'ownGoals': return s5 ? s5.ownGoals : 0;
                case 'yellowCards': return s5 ? s5.yellowCards : 0;
                case 'redCards': return s5 ? s5.redCards : 0;
                case 'penStopped': return s5 ? s5.penaltiesStopped : 0;
                case 'penMissed': return s5 ? s5.penaltiesMissed : 0;
                case 'causedPen': return s5 ? (s5.causedPenalty || 0) : 0;
                case 'failedPen': return s5 ? (s5.failedForPenalty || 0) : 0;
                case 'price': return player.price;
                default: return 0;
            }
        },

        getRoundStat(player, stat) {
            const rounds = Alpine.store('data').rounds || {};
            const rnd = rounds[this.roundFilter];
            if (!rnd || !rnd.players) return '-';
            const ps = rnd.players[String(player.id)];
            if (!ps) return '-';

            const s5 = ps.sport5 || {};
            const fc = ps.footballCoIl || {};
            const s3 = ps.scores365 || {};

            switch (stat) {
                case 'fantasyPoints': return s5.points || 0;
                case 'goals': return s5.goals || 0;
                case 'assists': return s5.assists || 0;
                case 'xG': return fc.expectedGoals != null ? fc.expectedGoals.toFixed(2) : '-';
                case 'rating': return s3.rating ? s3.rating.toFixed(1) : '-';
                case 'minutes': return s5.minutesPlayed || 0;
                case 'yellowCards': return s5.yellowCards || 0;
                case 'redCards': return s5.redCards || 0;
                default: return 0;
            }
        },

        getMultiRoundStat(player, stat) {
            const rounds = Alpine.store('data').rounds || {};
            const pid = String(player.id);
            let total = 0;
            let totalPts = 0;
            let found = false;

            // For ppm, we need total points regardless of which stat is requested
            const needPpm = (stat === 'ppm');
            const actualStat = needPpm ? 'fantasyPoints' : stat;

            for (const r of this.selectedRounds) {
                const rnd = rounds[String(r)];
                if (!rnd || !rnd.players) continue;
                const ps = rnd.players[pid];
                if (!ps) continue;
                found = true;
                const s5 = ps.sport5 || {};
                const fc = ps.footballCoIl || {};

                totalPts += s5.points || 0;

                switch (actualStat) {
                    case 'fantasyPoints': total += s5.points || 0; break;
                    case 'goals': total += s5.goals || 0; break;
                    case 'assists': total += s5.assists || 0; break;
                    case 'xG': total += fc.expectedGoals || 0; break;
                    case 'shotAttempts': total += fc.shotsOnTarget || 0; break;
                    case 'minutes': total += s5.minutesPlayed || 0; break;
                    case 'cleanSheets': total += s5.cleanSheets || 0; break;
                    case 'subIn': total += s5.substituteIn || 0; break;
                    case 'subOut': total += s5.substituteOut || 0; break;
                    case 'ownGoals': total += s5.ownGoals || 0; break;
                    case 'yellowCards': total += s5.yellowCards || 0; break;
                    case 'redCards': total += s5.redCards || 0; break;
                    case 'penStopped': case 'penMissed': case 'causedPen': case 'failedPen': break;
                }
            }

            if (!found) return '-';
            if (needPpm) return player.price > 0 && totalPts > 0 ? (totalPts / (player.price / 1000000)).toFixed(1) : '-';
            if (stat === 'xG') return total > 0 ? total.toFixed(2) : '-';
            if (stat === 'xA' || stat === 'xGI') return '-';
            if (stat === 'price') return player.price;
            return total;
        },

        getNumericStat(player, stat) {
            const val = this.getStat(player, stat);
            return typeof val === 'number' ? val : parseFloat(val) || 0;
        },

        totalPages() {
            return Math.ceil(this.filtered().length / this.pageSize) || 1;
        },

        paginated() {
            const f = this.filtered();
            const start = (this.currentPage - 1) * this.pageSize;
            return f.slice(start, start + this.pageSize);
        },

        filtered() {
            // Only show players who are in the Sport5 game (have minutes)
            let list = Alpine.store('data').players.filter(p => p.sport5 && p.sport5.minutesPlayed > 0);

            if (this.search) {
                const q = this.search.toLowerCase();
                list = list.filter(p =>
                    p.name.toLowerCase().includes(q) ||
                    (p.englishName && p.englishName.toLowerCase().includes(q))
                );
            }
            if (this.posFilter) {
                list = list.filter(p => p.position == this.posFilter);
            }
            if (this.teamFilter) {
                list = list.filter(p => p.teamId == this.teamFilter);
            }
            if (this.maxPriceM) {
                list = list.filter(p => p.price <= this.maxPriceM * 1000000);
            }

            const dir = this.sortDesc ? -1 : 1;
            list.sort((a, b) => dir * (this.getNumericStat(a, this.sortBy) - this.getNumericStat(b, this.sortBy)));
            return list;
        }
    };
}

// -- Player Detail Component --

function playerDetail() {
    return {
        player: null,
        _chart: null,
        posLabel, posClass, formatPrice,

        loadPlayer() {
            const param = Alpine.evaluate(this.$el.closest('[x-data="app()"]'), 'pageParam');
            if (!param) return;
            this.player = Alpine.store('data').getPlayer(param);
            // Double nextTick: first for x-if to render, second for canvas to be in DOM
            this.$nextTick(() => this.$nextTick(() => this.buildChart()));
        },

        playerRounds() {
            if (!this.player) return [];
            const rounds = Alpine.store('data').rounds || {};
            const pid = String(this.player.id);
            const result = [];

            for (const [rndKey, rndData] of Object.entries(rounds)) {
                const ps = rndData.players ? rndData.players[pid] : null;
                if (!ps) continue;
                const s5 = ps.sport5 || {};
                const fc = ps.footballCoIl || {};
                const s3 = ps.scores365 || {};
                result.push({
                    round: parseInt(rndKey),
                    points: s5.points || 0,
                    goals: s5.goals || 0,
                    assists: s5.assists || 0,
                    minutes: s5.minutesPlayed || 0,
                    xG: fc.expectedGoals != null ? fc.expectedGoals.toFixed(2) : '-',
                });
            }

            result.sort((a, b) => a.round - b.round);
            return result;
        },

        buildChart() {
            const canvas = document.getElementById('playerChart');
            if (!canvas || !this.player) return;

            if (this._chart) this._chart.destroy();

            const rds = this.playerRounds();
            if (!rds.length) return;

            const labels = rds.map(r => 'מחזור ' + r.round);
            const points = rds.map(r => r.points);
            const goals = rds.map(r => r.goals);
            const xG = rds.map(r => parseFloat(r.xG) || 0);

            this._chart = new Chart(canvas, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [
                        {
                            label: 'נקודות פנטזי',
                            data: points,
                            backgroundColor: 'rgba(59, 130, 246, 0.7)',
                            order: 3,
                            yAxisID: 'y',
                        },
                        {
                            label: 'שערים',
                            type: 'bar',
                            data: goals,
                            backgroundColor: 'rgba(239, 68, 68, 0.7)',
                            order: 2,
                            yAxisID: 'y1',
                        },
                        {
                            label: 'xG',
                            type: 'line',
                            data: xG,
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.1)',
                            fill: true,
                            tension: 0.3,
                            pointRadius: 4,
                            order: 1,
                            yAxisID: 'y1',
                        }
                    ]
                },
                options: {
                    responsive: true,
                    interaction: { mode: 'index', intersect: false },
                    plugins: { legend: { position: 'top' } },
                    scales: {
                        y: { type: 'linear', position: 'right', title: { display: true, text: 'נקודות' }, beginAtZero: true },
                        y1: { type: 'linear', position: 'left', title: { display: true, text: 'שערים / xG' }, beginAtZero: true, grid: { drawOnChartArea: false } }
                    }
                }
            });
        }
    };
}

// -- Team Detail Component --

function teamDetail() {
    return {
        team: null,
        teamSort: 'points',
        posLabel, posClass, formatPrice,

        loadTeam() {
            const param = Alpine.evaluate(this.$el.closest('[x-data="app()"]'), 'pageParam');
            if (!param) return;
            this.team = Alpine.store('data').getTeam(param);
        },

        teamPlayers() {
            if (!this.team) return [];
            const ids = new Set(this.team.playerIds || []);
            let list = Alpine.store('data').players
                .filter(p => ids.has(p.id) && p.sport5 && p.sport5.minutesPlayed > 0);

            const desc = this.teamSort.startsWith('-');
            const key = desc ? this.teamSort.slice(1) : this.teamSort;
            const dir = desc ? 1 : -1;

            list.sort((a, b) => {
                let va, vb;
                switch (key) {
                    case 'position': va = a.position || 99; vb = b.position || 99; break;
                    case 'price': va = a.price; vb = b.price; break;
                    case 'points': va = a.sport5 ? a.sport5.totalPoints : 0; vb = b.sport5 ? b.sport5.totalPoints : 0; break;
                    case 'ppm': va = a.ppm || 0; vb = b.ppm || 0; break;
                    case 'goals': va = a.sport5 ? a.sport5.goals : 0; vb = b.sport5 ? b.sport5.goals : 0; break;
                    case 'assists': va = a.sport5 ? a.sport5.assists : 0; vb = b.sport5 ? b.sport5.assists : 0; break;
                    case 'xG': va = a.footballCoIl ? a.footballCoIl.expectedGoals : 0; vb = b.footballCoIl ? b.footballCoIl.expectedGoals : 0; break;
                    default: va = 0; vb = 0;
                }
                return dir * (va - vb);
            });
            return list;
        }
    };
}

// -- Rounds Browser Component --

function roundsBrowser() {
    return {
        selectedRound: 1,
        posTab: '',
        posLabel, posClass, formatPrice,

        get availableRounds() {
            return Object.keys(Alpine.store('data').rounds || {}).map(Number).sort((a, b) => a - b);
        },

        initRounds() {
            const rounds = this.availableRounds;
            if (rounds.length) this.selectedRound = rounds[rounds.length - 1];
        },

        topPerformers() {
            const rnd = Alpine.store('data').rounds[String(this.selectedRound)];
            if (!rnd || !rnd.players) return [];

            const entries = [];
            for (const [pid, stats] of Object.entries(rnd.players)) {
                const player = Alpine.store('data').getPlayer(pid);
                if (!player) continue;
                const pts = stats.sport5 ? stats.sport5.points || 0 : 0;
                entries.push({ id: player.id, name: player.name, team: player.team, points: pts });
            }
            entries.sort((a, b) => b.points - a.points);
            return entries.slice(0, 5);
        },

        roundPlayers() {
            const rnd = Alpine.store('data').rounds[String(this.selectedRound)];
            if (!rnd || !rnd.players) return [];

            const entries = [];
            for (const [pid, stats] of Object.entries(rnd.players)) {
                const player = Alpine.store('data').getPlayer(pid);
                if (!player) continue;
                if (this.posTab && player.position != this.posTab) continue;

                const s5 = stats.sport5 || {};
                const fc = stats.footballCoIl || {};
                const s3 = stats.scores365 || {};

                entries.push({
                    id: player.id,
                    name: player.name,
                    team: player.team,
                    position: player.position,
                    points: s5.points || 0,
                    goals: s5.goals || 0,
                    assists: s5.assists || 0,
                    minutes: s5.minutesPlayed || 0,
                    xG: fc.expectedGoals != null ? fc.expectedGoals.toFixed(2) : '-',
                    rating: s3.rating ? s3.rating.toFixed(1) : '-',
                });
            }
            entries.sort((a, b) => b.points - a.points);
            return entries;
        }
    };
}

// -- Leaders Page Component --

function leadersPage() {
    return {
        activeCat: 'goals',
        categories: [
            { key: 'fantasyPoints', label: 'נקודות פנטזי' },
            { key: 'ppm', label: 'PPM' },
            { key: 'goals', label: 'שערים' },
            { key: 'expectedGoals', label: 'xG' },
            { key: 'assists', label: 'בישולים' },
            { key: 'xA', label: 'xA' },
            { key: 'xGI', label: 'xGI' },
            { key: 'rating', label: 'דירוג' },
            { key: 'cleanSheets', label: 'שער נקי' },
            { key: 'yellowCards', label: 'צהובים' },
            { key: 'minutesPlayed', label: 'דקות' },
        ],

        currentLeaders() {
            return Alpine.store('data').leaders[this.activeCat] || [];
        },

        barWidth(value) {
            const leaders = this.currentLeaders();
            if (!leaders.length) return 0;
            const max = leaders[0].value || 1;
            return Math.round((value / max) * 100);
        }
    };
}

// -- Compare Page Component --

function comparePage() {
    return {
        search1: '',
        search2: '',
        player1: null,
        player2: null,
        _radar: null,
        posLabel,

        initCompare() {},

        searchResults(query) {
            if (!query || query.length < 2) return [];
            const q = query.toLowerCase();
            return Alpine.store('data').players
                .filter(p => p.sport5 && p.sport5.minutesPlayed > 0 &&
                    (p.name.toLowerCase().includes(q) || (p.englishName && p.englishName.toLowerCase().includes(q))))
                .slice(0, 8);
        },

        selectPlayer(num, p) {
            if (num === 1) { this.player1 = p; this.search1 = ''; }
            else { this.player2 = p; this.search2 = ''; }
            this.$nextTick(() => this.$nextTick(() => this.buildRadar()));
        },

        _val(p, key) {
            const s5 = p.sport5 || {};
            const fc = p.footballCoIl || {};
            const s3 = p.scores365 || {};
            switch (key) {
                case 'points': return s5.totalPoints || 0;
                case 'goals': return s5.goals || 0;
                case 'assists': return s5.assists || 0;
                case 'xG': return s3.xG || fc.expectedGoals || 0;
                case 'xA': return p.xA || 0;
                case 'minutes': return s5.minutesPlayed || 0;
                case 'cleanSheets': return s5.cleanSheets || 0;
                case 'rating': return s3.rating || 0;
                case 'ppm': return p.ppm || 0;
                case 'shots': return s3.totalShots || fc.shotAttempts || 0;
                case 'touches': return s3.touches || 0;
                case 'yellowCards': return s5.yellowCards || 0;
                case 'appearances': return s3.appearances || (s5.openLineup + s5.substituteIn) || 0;
                default: return 0;
            }
        },

        comparisonRows() {
            if (!this.player1 || !this.player2) return [];
            const stats = [
                { key: 'points', label: 'נקודות פנטזי', fmt: v => v },
                { key: 'ppm', label: 'PPM', fmt: v => v.toFixed(1) },
                { key: 'goals', label: 'שערים', fmt: v => v },
                { key: 'assists', label: 'בישולים', fmt: v => v },
                { key: 'xG', label: 'xG', fmt: v => v.toFixed(2) },
                { key: 'xA', label: 'xA', fmt: v => v.toFixed(2) },
                { key: 'rating', label: 'דירוג', fmt: v => v > 0 ? v.toFixed(1) : '-' },
                { key: 'minutes', label: 'דקות', fmt: v => v },
                { key: 'appearances', label: 'הופעות', fmt: v => v },
                { key: 'shots', label: 'בעיטות', fmt: v => v },
                { key: 'touches', label: 'נגיעות', fmt: v => v > 0 ? v : '-' },
                { key: 'cleanSheets', label: 'שער נקי', fmt: v => v },
                { key: 'yellowCards', label: 'צהובים', fmt: v => v },
            ];
            return stats.map(s => {
                const v1 = this._val(this.player1, s.key);
                const v2 = this._val(this.player2, s.key);
                // For yellow cards, lower is better
                const inv = s.key === 'yellowCards';
                return {
                    label: s.label,
                    v1: inv ? -v1 : v1,
                    v2: inv ? -v2 : v2,
                    d1: s.fmt(v1),
                    d2: s.fmt(v2),
                };
            });
        },

        buildRadar() {
            const canvas = document.getElementById('radarChart');
            if (!canvas || !this.player1 || !this.player2) return;
            if (this._radar) this._radar.destroy();

            // Normalize stats to 0-100 scale for radar
            const dims = [
                { key: 'points', label: 'נקודות' },
                { key: 'goals', label: 'שערים' },
                { key: 'assists', label: 'בישולים' },
                { key: 'xG', label: 'xG' },
                { key: 'xA', label: 'xA' },
                { key: 'rating', label: 'דירוג' },
                { key: 'ppm', label: 'PPM' },
                { key: 'shots', label: 'בעיטות' },
            ];

            const labels = dims.map(d => d.label);
            const raw1 = dims.map(d => this._val(this.player1, d.key));
            const raw2 = dims.map(d => this._val(this.player2, d.key));

            // Normalize each dimension to 0-100
            const data1 = [];
            const data2 = [];
            for (let i = 0; i < dims.length; i++) {
                const max = Math.max(raw1[i], raw2[i], 0.01);
                data1.push(Math.round(raw1[i] / max * 100));
                data2.push(Math.round(raw2[i] / max * 100));
            }

            this._radar = new Chart(canvas, {
                type: 'radar',
                data: {
                    labels,
                    datasets: [
                        {
                            label: this.player1.name,
                            data: data1,
                            borderColor: '#3b82f6',
                            backgroundColor: 'rgba(59, 130, 246, 0.15)',
                            pointBackgroundColor: '#3b82f6',
                        },
                        {
                            label: this.player2.name,
                            data: data2,
                            borderColor: '#f97316',
                            backgroundColor: 'rgba(249, 115, 22, 0.15)',
                            pointBackgroundColor: '#f97316',
                        }
                    ]
                },
                options: {
                    responsive: true,
                    scales: {
                        r: {
                            beginAtZero: true,
                            max: 100,
                            ticks: { display: false },
                            grid: { color: 'rgba(0,0,0,0.08)' },
                            pointLabels: { font: { size: 12 } },
                        }
                    },
                    plugins: {
                        legend: { position: 'top' },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => {
                                    const dim = dims[ctx.dataIndex];
                                    const p = ctx.datasetIndex === 0 ? this.player1 : this.player2;
                                    return ctx.dataset.label + ': ' + this._val(p, dim.key);
                                }
                            }
                        }
                    }
                }
            });
        }
    };
}
