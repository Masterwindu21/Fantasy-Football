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

      # ================= TRADES AUSLESEN (ROH-ENDPOINT) =================
      try:
        # Direkte Abfrage des Kommunikations- und Transaktions-Views von ESPN
        params = {"view": "mTransactions2"}
        endpoint = (
            f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}/segments/0/leagues/{LEAGUE_ID}"
        )
        data = league.espn_request.league_get(params=params)

        transactions = data.get("transactions", [])
        seen_trades = set()

        for t in transactions:
          # ESPN markiert Trades als executionType / type == 'TRADE'
          t_type = t.get("type", "")
          t_status = t.get("status", "")

          if "TRADE" in t_type.upper() and t_status.upper() in [
              "EXECUTED",
              "ACCEPTED",
              "COMPLETE",
          ]:
            items = t.get("items", [])
            involved_teams = set()

            for item in items:
              from_team = item.get("fromTeamId")
              to_team = item.get("toTeamId")
              if from_team and from_team > 0:
                involved_teams.add(from_team)
              if to_team and to_team > 0:
                involved_teams.add(to_team)

            if len(involved_teams) == 2:
              t_list = sorted(list(involved_teams))
              trade_sig = (t.get("proposedDate", t.get("id")), t_list[0], t_list[1])

              if trade_sig in seen_trades:
                continue
              seen_trades.add(trade_sig)

              m1 = team_id_to_owner.get(t_list[0])
              m2 = team_id_to_owner.get(t_list[1])

              if m1 and m2 and m1 != m2:
                stats[m1]["trades"] += 1
                stats[m2]["trades"] += 1
                trade_partners[m1][m2] += 1
                trade_partners[m2][m1] += 1

      except Exception:
        # Fallback auf recent_activity, falls mTransactions2 nicht greift
        try:
          activities = league.recent_activity(size=500)
          for act in activities:
            actions = getattr(act, "actions", [])
            trade_actions = [
                a
                for a in actions
                if len(a) >= 2 and str(a[1]).upper() == "TRADED"
            ]
            if trade_actions:
              inv = list(
                  {
                      a[0].team_id
                      for a in trade_actions
                      if hasattr(a[0], "team_id")
                  }
              )
              if len(inv) == 2:
                m1 = team_id_to_owner.get(inv[0])
                m2 = team_id_to_owner.get(inv[1])
                if m1 and m2 and m1 != m2:
                  stats[m1]["trades"] += 1
                  stats[m2]["trades"] += 1
                  trade_partners[m1][m2] += 1
                  trade_partners[m2][m1] += 1
        except Exception:
          pass

    except Exception:
      pass

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

    partner_counts = trade_partners[manager]
    if partner_counts:
      top_p, count = partner_counts.most_common(1)[0]
      fav_partner = f"{top_p} ({count}x)"
    else:
      fav_partner = "–"

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
        "Trades": s["trades"],
        "Lieblingspartner": fav_partner,
    })

  return formatted_data
