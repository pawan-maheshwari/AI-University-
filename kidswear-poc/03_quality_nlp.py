"""
Step 3 - Return-comment intelligence with continuous learning.

1. Reason classifier (TF-IDF word + character n-grams -> logistic regression).
   * Frozen model: trained on FY2025 verified comments only.
   * Refreshed model: retrained automatically with FY2026 verified comments up to week 90
     (customers started using new words in FY2026).
   * Both scored on FY2026 verified comments from weeks 91-104 (held out).
2. Apply the refreshed model to every comment and rank FY2026 styles by quality-driven return value.
3. Themes (top phrases per style) and suggested actions for Quality and Buying.
4. Hand a per-comment reason file to the demand model (quality signal feature) and the markdown optimiser.
"""
import json, os
import numpy as np
import pandas as pd
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import make_pipeline, make_union
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score, confusion_matrix
import paths
from governance_lib import audit_log, register_run, write_json, file_hash

c = pd.read_csv(os.path.join(paths.RAW, "returns_comments.csv"), dtype={"verified_reason": str})
c["comment"] = c.comment.fillna(""); c["verified_reason"] = c.verified_reason.fillna("")
styles = pd.read_csv(os.path.join(paths.RAW, "style_master.csv"))
truth = pd.read_csv(os.path.join(paths.GT, "style_truth_FY2026.csv"))[["style_id", "quality_issue"]]
lab = c[c.verified_reason != ""]
QUALITY = ["fit", "fabric", "durability"]
ACTIONS = {
    "fit": "Fit session on three sizes; re-check grading and the pattern block with the supplier before the next buy.",
    "fabric": "Wash-test the fabric for shrinkage, pilling and colour-fastness; tighten the fabric specification.",
    "durability": "Seam, trim and fastening strength tests; supplier QA audit and a pre-shipment inspection.",
}


def build(C):
    return make_pipeline(make_union(TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True),
                                    TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True)),
                         LogisticRegression(C=C, max_iter=3000, class_weight="balanced"))


def tune(train):
    tr, va = train_test_split(train, test_size=0.2, stratify=train.verified_reason, random_state=1)
    scores = []
    for C in (1, 3, 10):
        m = build(C).fit(tr.comment, tr.verified_reason)
        scores.append((f1_score(va.verified_reason, m.predict(va.comment), average="macro"), C))
    f1, C = max(scores)
    return build(C).fit(train.comment, train.verified_reason), C, f1


fy25 = lab[lab.season == "FY2025"]
fy26_seen = lab[(lab.season == "FY2026") & (lab.week_index <= 90)]
test = lab[lab.week_index >= 91]
frozen, C1, f1v1 = tune(fy25)
refreshed, C2, f1v2 = tune(pd.concat([fy25, fy26_seen]))
new_words = test.comment.str.contains("boxy|crotch|rides up|proportions|lint|bled|stiff|fluff|burst|strap|velcro|wore through", case=False)
labels = sorted(lab.verified_reason.unique())


def score(m, d):
    return round(float(f1_score(d.verified_reason, m.predict(d.comment), average="macro")), 4)


learning = dict(frozen=dict(trained_on="FY2025 verified comments", n=len(fy25), C=C1, test_macro_f1=score(frozen, test),
                            test_macro_f1_new_phrasing=score(frozen, test[new_words])),
                refreshed=dict(trained_on="FY2025 + FY2026 verified comments to week 90", n=len(fy25) + len(fy26_seen), C=C2,
                               test_macro_f1=score(refreshed, test), test_macro_f1_new_phrasing=score(refreshed, test[new_words])),
                test=dict(rows=len(test), new_phrasing_rows=int(new_words.sum()), weeks="91-104"),
                confusion_matrix=dict(labels=labels, matrix=confusion_matrix(test.verified_reason, refreshed.predict(test.comment), labels=labels).tolist()))
learning["refresh_gain_pts"] = round((learning["refreshed"]["test_macro_f1"] - learning["frozen"]["test_macro_f1"]) * 100, 1)
joblib.dump(refreshed, os.path.join(paths.MOD, "returns_reason_classifier.joblib"))

# apply to all comments
c["reason_pred"] = refreshed.predict(c.comment)
c["reason_used"] = np.where(c.verified_reason != "", c.verified_reason, c.reason_pred)
c["is_quality"] = c.reason_used.isin(QUALITY).astype(int)
c[["comment_id", "style_id", "store_id", "season", "week_index", "reason_used", "is_quality"]] \
    .to_csv(os.path.join(paths.SPL, "comment_reasons.csv"), index=False)

# FY2026 ranking (to week 104)
sales = pd.read_csv(os.path.join(paths.RAW, "sales_weekly.csv.gz"), usecols=["season", "style_id", "sales_units", "return_units"])
sales = sales[sales.season == "FY2026"].groupby("style_id")[["sales_units", "return_units"]].sum()
cy = c[c.season == "FY2026"]
mix = cy.groupby("style_id").agg(comments=("comment_id", "size"), quality_share=("is_quality", "mean"))
top_issue = cy[cy.is_quality == 1].groupby("style_id").reason_used.agg(lambda r: r.mode().iat[0]).rename("top_issue")
issue_mix = cy[cy.is_quality == 1].groupby(["style_id", "reason_used"]).size().unstack(fill_value=0)
rank = styles.set_index("style_id").join(sales).join(mix).join(top_issue).join(truth.set_index("style_id"))
rank["top_issue"] = rank.top_issue.fillna("none")
rank["return_rate"] = rank.return_units / rank.sales_units
rank["quality_return_units"] = rank.return_units * rank.quality_share
rank["quality_return_value_rand"] = rank.quality_return_units * rank.full_price
rank["quality_score"] = rank.return_rate * rank.quality_share
rank = rank[rank.sales_units > 0].sort_values("quality_score", ascending=False).reset_index()
rank["rank"] = np.arange(1, len(rank) + 1)

# themes: phrases over-represented in a style's quality comments versus all quality comments
qc = cy[cy.is_quality == 1]
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
FILLER = {"bought", "daughter", "son", "nephew", "gift", "usually", "love", "kids", "kid", "clothes", "school", "uniform",
          "item", "refund", "disappointed", "happy", "eish", "mainly", "age", "right", "size", "old", "cousin"}
vec = TfidfVectorizer(ngram_range=(2, 3), min_df=3, stop_words=list(ENGLISH_STOP_WORDS | FILLER))
docs = qc.groupby("style_id").comment.apply(" ".join)
Xd = vec.fit_transform(docs.values)
terms = np.array(vec.get_feature_names_out())
def pick_themes(row, k=3):
    out = []
    for t in terms[np.argsort(-row)]:
        if any(t in o or o in t or len(set(t.split()) & set(o.split())) >= 2 for o in out):
            continue
        out.append(t)
        if len(out) == k:
            break
    return out


themes = {sid: pick_themes(Xd[i].toarray()[0]) for i, sid in enumerate(docs.index)}
rank["themes"] = rank.style_id.map(lambda s: themes.get(s, []))
rank["suggested_action"] = rank.top_issue.map(lambda t: ACTIONS.get(t, "Monitor; no dominant quality issue."))
rank["issue_mix"] = rank.style_id.map(lambda s: {k: int(v) for k, v in issue_mix.loc[s].items()} if s in issue_mix.index else {})
n_bad = int((rank.quality_issue != "none").sum())
by_rate = rank.sort_values("return_rate", ascending=False)
out = dict(
    continuous_learning=learning,
    styles_with_true_defect=n_bad,
    precision_at_10=round(float((rank.head(10).quality_issue != "none").mean()), 3),
    recall_at_n=round(float((rank.head(n_bad).quality_issue != "none").sum() / max(n_bad, 1)), 3),
    defect_type_correct_in_top_n=round(float((rank.head(n_bad).query("quality_issue != 'none'").top_issue ==
                                              rank.head(n_bad).query("quality_issue != 'none'").quality_issue).mean()), 3),
    baseline_return_rate_only_recall_at_n=round(float((by_rate.head(n_bad).quality_issue != "none").sum() / max(n_bad, 1)), 3),
    fy2026_quality_return_value_rand=round(float(rank.quality_return_value_rand.sum()), 0),
)
write_json("quality_nlp_metrics.json", out)
rank["confirmed_defect"] = np.where(rank.quality_issue != "none", "Yes", "No")
cols = ["rank", "style_id", "category", "supplier", "fabric", "fit", "sales_units", "return_units", "return_rate", "quality_share",
        "top_issue", "quality_return_value_rand", "themes", "suggested_action", "issue_mix", "confirmed_defect"]
rank[cols].round(4).to_json(paths.res("quality_dashboard.json"), orient="records", indent=1)
register_run("quality_nlp", model_version=file_hash(os.path.join(paths.MOD, "returns_reason_classifier.joblib")),
             params=dict(C=C2), training_window="FY2025 + FY2026 to week 90", metrics=learning["refreshed"])
audit_log("quality_ranking_published", top_styles=rank.head(5).style_id.tolist())
print(json.dumps({k: v for k, v in out.items() if k != "continuous_learning"}, indent=2))
print(json.dumps({k: learning[k] for k in ("frozen", "refreshed", "refresh_gain_pts")}, indent=2))
print(rank.head(8)[["rank", "style_id", "top_issue", "themes", "confirmed_defect"]].to_string(index=False))
