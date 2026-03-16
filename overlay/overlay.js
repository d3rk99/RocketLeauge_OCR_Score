const STATE_URLS = [
  '../data/match_state.json',
  '/data/match_state.json',
  'http://127.0.0.1:8000/data/match_state.json'
];

const refs = {
  teamAName: document.getElementById('teamAName'),
  teamAScore: document.getElementById('teamAScore'),
  teamAGames: document.getElementById('teamAGames'),
  teamBName: document.getElementById('teamBName'),
  teamBScore: document.getElementById('teamBScore'),
  teamBGames: document.getElementById('teamBGames'),
  seriesText: document.getElementById('seriesText'),
  statusText: document.getElementById('statusText')
};

function friendlySeries(seriesType) {
  if (!seriesType) return 'Best of ?';
  const n = seriesType.replace('bo', '');
  return `Best of ${n}`;
}

async function fetchState() {
  for (const url of STATE_URLS) {
    try {
      const response = await fetch(`${url}?t=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) continue;
      return await response.json();
    } catch (_) {
      // Try next source.
    }
  }
  return null;
}

function safeText(v, fallback = '-') {
  return (v === undefined || v === null || v === '') ? fallback : String(v);
}

function render(data) {
  if (!data) {
    refs.statusText.textContent = 'Waiting for state...';
    return;
  }

  refs.teamAName.textContent = safeText(data.team_a_name, 'Team A');
  refs.teamAScore.textContent = safeText(data.team_a_score, '0');
  refs.teamAGames.textContent = `Games: ${safeText(data.team_a_games, '0')}`;

  refs.teamBName.textContent = safeText(data.team_b_name, 'Team B');
  refs.teamBScore.textContent = safeText(data.team_b_score, '0');
  refs.teamBGames.textContent = `Games: ${safeText(data.team_b_games, '0')}`;

  refs.seriesText.textContent = friendlySeries(data.series_type);
  refs.statusText.textContent = safeText(data.match_status, 'idle');
}

async function tick() {
  const state = await fetchState();
  render(state);
}

setInterval(tick, 500);
tick();
