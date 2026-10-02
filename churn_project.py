"""
Telecom Customer Churn: Cleaning and SQL Analysis
Run:  python churn_project.py
Needs: pandas, matplotlib  (python -m pip install pandas matplotlib)
"""
import random
import sqlite3
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # saves charts to a file without opening a window
import matplotlib.pyplot as plt

random.seed(7)

# ---------- 1. Create a messy raw dataset (stand-in for real data) ----------
def make_raw_data(n=2000):
    plans = {"Basic": 3000, "Standard": 6000, "Premium": 12000}
    states = ["Lagos", "Abuja", "Oyo", "Osun", "Rivers", "Kano"]
    pay = ["Card", "Transfer", "USSD", "Cash"]
    rows = []
    for i in range(1, n + 1):
        plan = random.choice(list(plans))
        tenure = random.randint(1, 48)
        calls = random.choices([0, 1, 2, 3, 4, 5, 6], [30, 25, 18, 12, 8, 5, 2])[0]
        method = random.choice(pay)
        # churn is more likely with many support calls, short tenure, Basic plan, cash
        p = 0.08 + 0.06 * calls + (0.12 if tenure <= 6 else 0) + (0.08 if plan == "Basic" else 0)
        p += 0.05 if method == "Cash" else 0
        churn = "Yes" if random.random() < min(p, 0.85) else "No"
        usage = round(random.uniform(1, 60), 1)
        price = plans[plan]
        row = [f"CUST{i:05d}", random.choice(states), plan,
               f"₦{price:,}" if random.random() < 0.3 else str(price),
               tenure, usage, calls, method, churn]
        # introduce mess
        if random.random() < 0.12: row[1] = random.choice([f" {row[1].lower()} ", row[1].upper()])
        if random.random() < 0.10: row[2] = row[2].lower()
        if random.random() < 0.05: row[5] = None                      # missing usage
        if random.random() < 0.02: row[4] = -row[4]                   # bad tenure
        if random.random() < 0.08: row[8] = random.choice(["yes", "Y", "no", "N"])[:]
        if random.random() < 0.02: row[8] = None                      # missing churn label
        rows.append(row)
    df = pd.DataFrame(rows, columns=["customer_id", "state", "plan", "monthly_charge",
                                     "tenure_months", "data_usage_gb", "support_calls",
                                     "payment_method", "churned"])
    return pd.concat([df, df.sample(50, random_state=2)], ignore_index=True).sample(frac=1, random_state=5)

raw = make_raw_data()
raw.to_csv("raw_churn.csv", index=False)
print(f"Raw rows: {len(raw)}")

# ---------- 2. Clean with pandas ----------
df = raw.copy()
log = {}

log["duplicate rows removed"] = int(df.duplicated().sum())
df = df.drop_duplicates()

df["state"] = df["state"].str.strip().str.title()
df["plan"] = df["plan"].str.strip().str.title()

df["monthly_charge"] = (df["monthly_charge"].astype(str)
                        .str.replace("₦", "", regex=False).str.replace(",", "", regex=False)
                        .astype(float))

# Churn labels came in many forms (Yes, yes, Y, No, N): turn into 1 / 0
label_map = {"yes": 1, "y": 1, "no": 0, "n": 0}
df["churned"] = df["churned"].str.strip().str.lower().map(label_map)
log["rows dropped for missing churn label"] = int(df["churned"].isna().sum())
df = df.dropna(subset=["churned"]).copy()
df["churned"] = df["churned"].astype(int)

log["negative tenure rows dropped"] = int((df["tenure_months"] <= 0).sum())
df = df[df["tenure_months"] > 0].copy()

# Fill missing data usage with the median for that plan
log["missing data usage filled"] = int(df["data_usage_gb"].isna().sum())
df["data_usage_gb"] = df["data_usage_gb"].fillna(df.groupby("plan")["data_usage_gb"].transform("median"))

df.to_csv("clean_churn.csv", index=False)

print("\nCleaning log:")
for k, v in log.items():
    print(f"  {k}: {v}")
print(f"Clean rows: {len(df)}")

# ---------- 3. Load into SQLite and analyse with SQL ----------
con = sqlite3.connect("churn.db")
df.to_sql("customers", con, if_exists="replace", index=False)

queries = {
    "Overall churn rate": """
        SELECT COUNT(*) AS customers, SUM(churned) AS churned,
               ROUND(100.0 * SUM(churned) / COUNT(*), 1) AS churn_rate_pct
        FROM customers;""",
    "Churn rate by plan": """
        SELECT plan, COUNT(*) AS customers,
               ROUND(100.0 * SUM(churned) / COUNT(*), 1) AS churn_rate_pct
        FROM customers GROUP BY plan ORDER BY churn_rate_pct DESC;""",
    "Churn rate by number of support calls": """
        SELECT CASE WHEN support_calls = 0 THEN '0 calls'
                    WHEN support_calls <= 2 THEN '1-2 calls'
                    ELSE '3+ calls' END AS support_group,
               COUNT(*) AS customers,
               ROUND(100.0 * SUM(churned) / COUNT(*), 1) AS churn_rate_pct
        FROM customers GROUP BY support_group ORDER BY churn_rate_pct;""",
    "Churn rate by tenure": """
        SELECT CASE WHEN tenure_months <= 6 THEN '0-6 months'
                    WHEN tenure_months <= 24 THEN '7-24 months'
                    ELSE '25+ months' END AS tenure_group,
               COUNT(*) AS customers,
               ROUND(100.0 * SUM(churned) / COUNT(*), 1) AS churn_rate_pct
        FROM customers GROUP BY tenure_group ORDER BY churn_rate_pct DESC;""",
    "Churn rate by payment method": """
        SELECT payment_method, COUNT(*) AS customers,
               ROUND(100.0 * SUM(churned) / COUNT(*), 1) AS churn_rate_pct
        FROM customers GROUP BY payment_method ORDER BY churn_rate_pct DESC;""",
    "Monthly revenue lost to churn, by state": """
        SELECT state, SUM(monthly_charge) AS revenue_lost_per_month,
               RANK() OVER (ORDER BY SUM(monthly_charge) DESC) AS rank_lost
        FROM customers WHERE churned = 1
        GROUP BY state ORDER BY revenue_lost_per_month DESC;""",
    "Highest-risk segments (plan + support calls, 30+ customers)": """
        SELECT plan,
               CASE WHEN support_calls >= 3 THEN '3+ calls' ELSE '0-2 calls' END AS support_group,
               COUNT(*) AS customers,
               ROUND(100.0 * SUM(churned) / COUNT(*), 1) AS churn_rate_pct
        FROM customers GROUP BY plan, support_group
        HAVING COUNT(*) >= 30 ORDER BY churn_rate_pct DESC LIMIT 5;""",
}

results = {}
for title, q in queries.items():
    results[title] = pd.read_sql(q, con)
    print(f"\n{title}\n{results[title].to_string(index=False)}")

# ---------- 4. Charts ----------
fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
for a, (title, xcol) in zip(ax, [("Churn rate by plan", "plan"),
                                 ("Churn rate by number of support calls", "support_group"),
                                 ("Churn rate by tenure", "tenure_group")]):
    d = results[title]
    a.bar(d[xcol], d["churn_rate_pct"], color="#0f766e")
    a.set_title(title.replace("Churn rate by", "Churn % by"))
    a.set_ylabel("Churn rate (%)")
plt.tight_layout()
plt.savefig("churn_charts.png", dpi=150)
plt.close()
print("\nSaved: raw_churn.csv, clean_churn.csv, churn.db, churn_charts.png")
