from collections import Counter, defaultdict
from datetime import datetime
from espn_api.football import League
import pandas as pd
import streamlit as st

# ================= 1. SEITENKONFIGURATION =================
st.set_page_config(
    page_title="B.U.M.S. League History", page_icon="🏈", layout="wide"
)

# ================= 2. EINSTELLUNGEN =================
LEAGUE_ID = 35203
START_YEAR = 2014
CURRENT_YEAR = datetime.now().year

# API Credentials
SWID = "{3759A752-7B49-4018-99A7-527B49701821}"
ESPN_S2 = "AEAgg0lunSBGY7T2U26biXMf26T0JjWREwRdibosZahxrNqxXvUC6%2BU0Z4j2SMzhsGI3zp6wZQz4SaRNR4gdhZrlRJBBs7jCjhu7RX%2B9tz5v8D%2BFomTu6uIP%2FzA4G7Vnx0MFu86mKcW47UW%2BD4gCfNciA1zTHyX6PA6121V3%2BmXJ9lvgQE%2FmDzV2Hp%2BxmRWFWpJjLkFO5yArCUTpgO7Cx6tiUeznf9%2BN9KPkt5J%2BqPpdzB0iV1xYk39HdF2EN2rXz9ZIetc1nLl4V9fis5HyTb5rpQNtwseMAx3wCw1WAGI3QQ%3D%3D"


# ================= 3. HILFSFUNKTIONEN =================
def get_owner_name(team):
  """Hilfsfunktion zur zuverlässigen Ermittlung des Manager-Namens"""
  if hasattr(team, "owners") and team.owners:
    owner = team.owners[0]
    if isinstance(owner, dict):
      first = owner.get("firstName", "")
      last = owner.get("lastName", "")
      full = f"{first} {last}".strip()
      if full:
        return full
    elif isinstance(owner, str):
      return owner.strip()
  if hasattr(team, "owner") and team.owner:
    return str(team.owner).strip()
  return team.team_name


# ================= 4. DATENABFRAGE (MIT CACHE) =================
@st.cache_data(ttl=3600)
def fetch_league_data():
  stats = defaultdict(
      lambda: {
          "reg_wins": 0,
          "reg_losses": 0,
          "reg_ties": 0,
          "playoff_wins": 0,
          "playoff_losses": 0,
          "points_for": 0.0,
          "points_against": 0.0,
          "titles": 0,
          "runner_ups": 0,
          "playoff_apps": 0,
          "last_places": 0,
          "seasons": 0,
          "highscore": 0.0,
          "lowscore": float("inf"),
          "trades": 0,
      }
  )

  trade_partners = defaultdict(lambda: Counter())

  for year in range(START_YEAR, CURRENT_YEAR + 1):
    try:
      if SWID and ESPN_S2:
        league = League(
            league_id=LEAGUE_ID, year=year, espn_s2=ESPN_S2, swid=SWID
        )
      else:
        league = League(league_id=LEAGUE_ID, year=year)

      playoff_spots = getattr(league.settings, "playoff_team_count", 6)
      total_teams_in_year = len(league.teams)

      team_id_to_owner = {}
      for team in league.teams:
        owner = get_owner_name(team)
        team_id_to_owner[team.team_id] = owner

        reg_w = team.wins
        reg_l = team.losses
        reg_t = team.ties

        stats[owner]["reg_wins"] += reg_w
        stats[owner]["reg_losses"] += reg_l
        stats[owner]["reg_ties"] += reg_t
        stats[owner]["points_for"] += team.points_for
        stats[owner]["points_against"] += team.points_against
        stats[owner]["seasons"] += 1

        team_rank = getattr(
            team, "final_standing", getattr(team, "standing", 99)
        )
        is_season_over = year < CURRENT_YEAR
        is_championship_bracket = team_rank <= playoff_spots

        if is_season_over:
          if team_rank == 1:
            stats[owner]["titles"] += 1
          elif team_rank == 2:
            stats[owner]["runner_ups"] += 1
          if team_rank == total_teams_in_year:
            stats[owner]["last_places"] += 1
          if is_championship_bracket:
            stats[owner]["playoff_apps"] += 1

        if hasattr(team, "outcomes"):
          reg_games_played = reg_w + reg_l + reg_t
          post_season = team.outcomes[reg_games_played:]
          if is_championship_bracket:
            for outcome in post_season:
              if outcome in ["W", "WIN"]:
                stats[owner]["playoff_wins"] += 1
              elif outcome in ["L", "LOSS"]:
                stats[owner]["playoff_losses"] += 1

        if hasattr(team, "scores") and hasattr(team, "outcomes"):
          for score, outcome in zip(team.scores, team.outcomes):
            if outcome in ["W", "WIN", "L", "LOSS", "T", "TIE"] and score > 0:
              if score > stats[owner]["highscore"]:
                stats[owner]["highscore"] = score
              if score < stats[owner]["lowscore"]:
                stats[owner]["lowscore"] = score

      # ================= TRADES AUSLESEN =================
      try:
        # ESPN API Header & View für Transaktionen
        headers = {
            "x-fantasy-filter": (
                '{"filterTransactions":{"filterType":{"value":["TRADE"]}}}'
            )
        }
        data = league.espn_request.league_get(
            params={"view": "mTransactions2"}, headers=headers
        )

        transactions = []
        if isinstance(data, dict):
          transactions = data.get(
              "transactions",
              data.get("communication", {}).get("topics", []),
          )

        seen_trades = set()

        for t in transactions:
          # Prüfung auf ausgeführten Trade
          t_type = t.get("type", "")
          t_status = t.get("status", "")

          if "TRADE" in str(t_type).upper() and str(t_status).upper() in [
              "EXECUTED",
              "ACCEPTED",
              "COMPLETE",
          ]:
            trade_id = t.get("id") or t.get("proposedDate")
            if trade_id in seen_trades:
              continue
            seen_trades.add(trade_id)

            items = t.get("items", [])
            involved_teams = set()

            for item in items:
              f_id = item.get("fromTeamId")
              t_id = item.get("toTeamId")
              if f_id and f_id > 0:
                involved_teams.add(f_id)
              if t_id and t_id > 0:
                involved_teams.add(t_id)

            if len(involved_teams) == 2:
              team_a, team_b = list(involved_teams)
              m1 = team_id_to_owner.get(team_a)
              m2 = team_id_to_owner.get(team_b)

              if m1 and m2 and m1 != m2:
                stats[m1]["trades"] += 1
                stats[m2]["trades"] += 1
                trade_partners[m1][m2] += 1
                trade_partners[m2][m1] += 1
      except Exception:
        pass

# ================= 5. DASHBOARD UI =================
st.title("🏆 B.U.M.S. League - All-Time Dashboard")
st.markdown(
    "Willkommen in der Hall of Fame (und Hall of Shame) eurer Liga. Die Daten"
    " werden live über die ESPN API abgerufen!"
)

with st.spinner("Lade historische ESPN Daten..."):
  raw_data = fetch_league_data()

df = pd.DataFrame(raw_data)

if not df.empty:
  df = df.sort_values(by=["1. Platz", "PF"], ascending=[False, False])

  col1, col2, col3, col4 = st.columns(4)
  with col1:
    best_high = df.loc[df["High"].idxmax()]
    st.metric(
        label="All-Time Highscore 🚀",
        value=f"{best_high['High']} Pkt",
        delta=best_high["Manager"],
    )
  with col2:
    most_titles = df.loc[df["1. Platz"].idxmax()]
    st.metric(
        label="Meiste Titel 🥇",
        value=f"{most_titles['1. Platz']}",
        delta=most_titles["Manager"],
    )
  with col3:
    most_sackos = df.loc[df["Sacko"].idxmax()]
    st.metric(
        label="Meiste Sackos 💩",
        value=f"{most_sackos['Sacko']}",
        delta=most_sackos["Manager"],
        delta_color="inverse",
    )
  with col4:
    most_trades = df.loc[df["Trades"].idxmax()]
    st.metric(
        label="Trade-König 🤝",
        value=f"{most_trades['Trades']} Trades",
        delta=most_trades["Manager"],
    )

  st.divider()

  st.subheader("📊 Ewige Tabelle")
  st.dataframe(df, use_container_width=True, hide_index=True)

  st.divider()

  st.subheader("📈 Visuelle Auswertungen")
  tab1, tab2, tab3 = st.tabs(
      ["Erzielte Punkte (PF)", "Win Percentage", "Trade-Aktivität"]
  )

  with tab1:
    st.bar_chart(df.set_index("Manager")["PF"])

  with tab2:
    veterans = df[df["Saisons"] > 3]
    if not veterans.empty:
      st.bar_chart(veterans.set_index("Manager")["Win %"])
    else:
      st.info(
          "Zu wenige Daten für den Win Percentage Vergleich (Manager benötigen"
          " >3 Saisons)."
      )

  with tab3:
    st.bar_chart(df.set_index("Manager")["Trades"])
else:
  st.error(
      "Es konnten keine Daten geladen werden. Bitte überprüfe deine Liga-ID und"
      " Cookies (SWID / ESPN_S2)."
  )
