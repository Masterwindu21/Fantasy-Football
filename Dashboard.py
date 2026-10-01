from collections import defaultdict
from datetime import datetime
from espn_api.football import League
import pandas as pd
import streamlit as st

# ================= 1. SEITENKONFIGURATION =================
st.set_page_config(
    page_title="B.U.M.S. League History", page_icon="🏈", layout="wide"
)

# ================= 2. EINSTELLUNGEN =================
LEAGUE_ID = 35203  # Deine ESPN League ID
START_YEAR = 2014  # Startjahr der Liga
CURRENT_YEAR = datetime.now().year

# API Credentials
SWID = st.secrets["SWID"]
ESPN_S2 = st.secrets["ESPN_S2"]


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
      }
  )

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

      for team in league.teams:
        owner = get_owner_name(team)

        # 1. Regular Season Stats
        reg_w = team.wins
        reg_l = team.losses
        reg_t = team.ties

        stats[owner]["reg_wins"] += reg_w
        stats[owner]["reg_losses"] += reg_l
        stats[owner]["reg_ties"] += reg_t
        stats[owner]["points_for"] += team.points_for
        stats[owner]["points_against"] += team.points_against
        stats[owner]["seasons"] += 1

        # Rang des Teams ermitteln
        team_rank = getattr(
            team, "final_standing", getattr(team, "standing", 99)
        )
        is_season_over = year < CURRENT_YEAR
        is_championship_bracket = team_rank <= playoff_spots

        # 2. Auszeichnungen
        if is_season_over:
          if team_rank == 1:
            stats[owner]["titles"] += 1
          elif team_rank == 2:
            stats[owner]["runner_ups"] += 1
          if team_rank == total_teams_in_year:
            stats[owner]["last_places"] += 1
          if is_championship_bracket:
            stats[owner]["playoff_apps"] += 1

        # 3. Playoffs
        if hasattr(team, "outcomes"):
          reg_games_played = reg_w + reg_l + reg_t
          post_season = team.outcomes[reg_games_played:]
          if is_championship_bracket:
            for outcome in post_season:
              if outcome in ["W", "WIN"]:
                stats[owner]["playoff_wins"] += 1
              elif outcome in ["L", "LOSS"]:
                stats[owner]["playoff_losses"] += 1

        # 4. Rekorde
        if hasattr(team, "scores") and hasattr(team, "outcomes"):
          for score, outcome in zip(team.scores, team.outcomes):
            if outcome in ["W", "WIN", "L", "LOSS", "T", "TIE"] and score > 0:
              if score > stats[owner]["highscore"]:
                stats[owner]["highscore"] = score
              if score < stats[owner]["lowscore"]:
                stats[owner]["lowscore"] = score

    except Exception as e:
      pass

  # 5. Aufbereitung
  formatted_data = []
  for manager, s in stats.items():
    reg_games = s["reg_wins"] + s["reg_losses"] + s["reg_ties"]
    total_wins = s["reg_wins"] + s["playoff_wins"]
    total_games = reg_games + s["playoff_wins"] + s["playoff_losses"]

    win_pct = (
        ((total_wins + (0.5 * s["reg_ties"])) / total_games * 100)
        if total_games > 0
        else 0.0
    )
    diff = s["points_for"] - s["points_against"]
    avg_points = (s["points_for"] / reg_games) if reg_games > 0 else 0.0
    low_score_val = s["lowscore"] if s["lowscore"] != float("inf") else 0.0

    reg_record = (
        f"{s['reg_wins']}-{s['reg_losses']}-{s['reg_ties']}"
        if s["reg_ties"] > 0
        else f"{s['reg_wins']}-{s['reg_losses']}"
    )

    formatted_data.append({
        "Manager": manager,
        "Saisons": s["seasons"],
        "Reg W-L-T": reg_record,
        "PO W-L": f"{s['playoff_wins']}-{s['playoff_losses']}",
        "Win %": round(win_pct, 1),
        "POs": f"{s['playoff_apps']}/{s['seasons']}",
        "1. Platz": s["titles"],
        "2. Platz": s["runner_ups"],
        "Sacko": s["last_places"],
        "PF": round(s["points_for"], 1),
        "PA": round(s["points_against"], 1),
        "Diff": round(diff, 1),
        "Ø Pkt": round(avg_points, 1),
        "High": round(s["highscore"], 1),
        "Low": round(low_score_val, 1),
    })

  return formatted_data


# ================= 5. DASHBOARD UI =================
st.title("🏆 B.U.M.S. League - All-Time Dashboard")
st.markdown(
    "Willkommen in der Hall of Fame (und Hall of Shame) eurer Liga. Die Daten"
    " werden live über die ESPN API abgerufen!"
)

with st.spinner(
    "Lade historische ESPN Daten... (das kann beim ersten Mal ein paar Sekunden"
    " dauern)"
):
  raw_data = fetch_league_data()

df = pd.DataFrame(raw_data)

if not df.empty:
  df = df.sort_values(by=["1. Platz", "PF"], ascending=[False, False])

  col1, col2, col3 = st.columns(3)
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

  st.divider()

  st.subheader("📊 Ewige Tabelle")
  st.dataframe(df, use_container_width=True, hide_index=True)

  st.divider()

  st.subheader("📈 Visuelle Auswertungen")
  tab1, tab2 = st.tabs(["Erzielte Punkte (PF)", "Win Percentage"])

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
else:
  st.error(
      "Es konnten keine Daten geladen werden. Bitte überprüfe deine Liga-ID und"
      " Cookies (SWID / ESPN_S2)."
  )

