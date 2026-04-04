/**
 * Data loader — fetches all JSON files and provides an Alpine.js store.
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('data', {
        players: [],
        teams: [],
        rounds: {},
        leaders: {},
        meta: null,
        loaded: false,

        async load() {
            const base = './data/';
            try {
                const [playersRes, teamsRes, roundsRes, leadersRes, metaRes] = await Promise.all([
                    fetch(base + 'players.json'),
                    fetch(base + 'teams.json'),
                    fetch(base + 'rounds.json'),
                    fetch(base + 'leaders.json'),
                    fetch(base + 'meta.json'),
                ]);

                if (!playersRes.ok) throw new Error('Failed to load players.json');

                const playersData = await playersRes.json();
                const teamsData = await teamsRes.json();
                const roundsData = await roundsRes.json();
                const leadersData = await leadersRes.json();
                const metaData = await metaRes.json();

                this.players = playersData.players || [];
                this.teams = (teamsData.teams || []).sort((a, b) => {
                    const pa = a.standings ? a.standings.position : 99;
                    const pb = b.standings ? b.standings.position : 99;
                    return pa - pb;
                });
                this.rounds = roundsData.rounds || {};
                this.leaders = leadersData;
                this.meta = metaData;
                this.loaded = true;
            } catch (err) {
                console.error('Data load error:', err);
                throw err;
            }
        },

        getPlayer(id) {
            return this.players.find(p => p.id === parseInt(id));
        },

        getTeam(id) {
            return this.teams.find(t => t.id === parseInt(id));
        }
    });
});
