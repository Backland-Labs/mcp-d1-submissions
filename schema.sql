CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_name TEXT NOT NULL,
  github_url TEXT NOT NULL,
  problem_statement TEXT NOT NULL,
  submitted_at TEXT NOT NULL
);
