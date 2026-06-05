# Deploy + Phase 6 Personal Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the static site to Netlify and add a personal portfolio layer where users enter their skills and see their "holdings" vs the market.

**Architecture:** Two sequential tracks — (1) create `netlify.toml` + push to GitHub + connect Netlify auto-deploy; (2) add a portfolio panel to the existing `public/index.html` using `localStorage` for persistence. No new data, no backend changes.

**Tech Stack:** Vanilla JS, localStorage, existing Chart.js + CSS vars. Python pipeline unchanged.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `netlify.toml` | Create | Tells Netlify to serve `public/` as the site root |
| `public/index.html` | Modify | Add portfolio panel: skill picker, holdings table, gap list |

---

## Task 1: Netlify deployment config

**Files:**
- Create: `netlify.toml`

- [ ] **Step 1: Create `netlify.toml`**

```toml
[build]
  publish = "public"

[[headers]]
  for = "/*"
  [headers.values]
    Cache-Control = "public, max-age=3600"
```

- [ ] **Step 2: Push repo to GitHub**

```bash
git remote add origin https://github.com/<your-username>/skill-stock.git
git push -u origin main
```

Replace `<your-username>` with your GitHub username. Create the repo at github.com/new first (public, no README).

- [ ] **Step 3: Connect Netlify**

1. Go to app.netlify.com → "Add new site" → "Import an existing project"
2. Pick GitHub → select `skill-stock`
3. Build settings: **Build command** = _(leave blank)_, **Publish directory** = `public`
4. Click "Deploy site"

Expected: Netlify shows a live URL like `https://skill-stock-xyz.netlify.app`. The site loads with the skills table.

- [ ] **Step 4: Add GitHub Actions secrets**

Repo → Settings → Secrets and variables → Actions → New repository secret. Add:
- `ADZUNA_APP_ID` = `2c57a774`
- `ADZUNA_APP_KEY` = (your key)
- `FIRECRAWL_API_KEY` = (your key)

`GITHUB_TOKEN` is automatically available — no manual step.

- [ ] **Step 5: Commit netlify.toml**

```bash
git add netlify.toml
git commit -m "chore: add Netlify deployment config"
git push
```

Expected: Netlify auto-deploys from the push. Check the Netlify dashboard for "Published".

---

## Task 2: Portfolio panel HTML + CSS

**Files:**
- Modify: `public/index.html`

Add a "My Portfolio" section between the movers section and the skills table section.

- [ ] **Step 1: Add portfolio CSS**

Find in `public/index.html`:
```css
  /* ── Scarcity meter ───────────────────────── */
```

Insert before it:
```css
  /* ── Portfolio panel ──────────────────────── */
  #portfolio-section {
    max-width: 1200px;
    margin: 0 auto 32px;
    padding: 0 24px;
  }
  #portfolio-toggle {
    background: none;
    border: 1px solid var(--border);
    color: var(--muted);
    font-family: inherit;
    font-size: 11px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 6px 14px;
    border-radius: 4px;
    cursor: pointer;
    margin-bottom: 16px;
  }
  #portfolio-toggle:hover { color: var(--text-bright); border-color: var(--green); }
  #portfolio-body { display: none; }
  #portfolio-body.open { display: block; }
  .portfolio-picker {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 20px;
  }
  .pick-chip {
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 4px 12px;
    font-size: 11px;
    cursor: pointer;
    color: var(--muted);
    background: none;
    font-family: inherit;
    transition: all 0.15s;
  }
  .pick-chip.selected {
    border-color: var(--green);
    color: var(--green);
    background: #00e67611;
  }
  #portfolio-holdings {
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    margin-bottom: 20px;
  }
  #portfolio-holdings table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  #portfolio-holdings th {
    text-align: left;
    font-size: 9px;
    letter-spacing: 0.1em;
    color: var(--muted);
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    background: #0a100a;
  }
  #portfolio-holdings td {
    padding: 10px 16px;
    border-bottom: 1px solid #1a221a;
  }
  #portfolio-holdings tr:last-child td { border-bottom: none; }
  #portfolio-empty {
    color: var(--muted);
    font-size: 12px;
    padding: 16px 0;
  }
  #gap-list h3 {
    font-size: 10px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 12px;
  }
  .gap-chip {
    display: inline-block;
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 4px 12px;
    font-size: 11px;
    color: var(--green);
    margin: 4px;
    cursor: pointer;
  }
  .gap-chip:hover { border-color: var(--green); }
```

- [ ] **Step 2: Add portfolio HTML**

Find in `public/index.html`:
```html
<section id="movers-section">
```

Insert AFTER the closing `</section>` tag of the movers section (find `</section>` that follows the movers grid):
```html
<section id="portfolio-section">
  <button id="portfolio-toggle" onclick="togglePortfolio()">⊕ My Portfolio</button>
  <div id="portfolio-body">
    <div class="portfolio-picker" id="skill-picker"></div>
    <div id="portfolio-holdings">
      <table>
        <thead>
          <tr>
            <th>SKILL</th>
            <th>PRICE</th>
            <th>MOM</th>
            <th>SAT</th>
            <th>COUNT</th>
          </tr>
        </thead>
        <tbody id="portfolio-rows"></tbody>
      </table>
    </div>
    <div id="portfolio-empty" style="display:none">Select skills above to build your portfolio.</div>
    <div id="gap-list"></div>
  </div>
</section>
```

- [ ] **Step 3: Commit**

```bash
git add public/index.html
git commit -m "feat: portfolio panel HTML and CSS scaffold"
```

---

## Task 3: Portfolio logic — skill picker + localStorage

**Files:**
- Modify: `public/index.html` (JS section)

- [ ] **Step 1: Add portfolio state + persistence helpers**

In `public/index.html`, find the line:
```javascript
// ── Utilities ────────────────────────────────────────────────────────────────
```

Insert BEFORE it:
```javascript
// ── Portfolio state ───────────────────────────────────────────────────────────
const PORTFOLIO_KEY = "skill-stock-portfolio-v1";

function loadPortfolio() {
  try { return new Set(JSON.parse(localStorage.getItem(PORTFOLIO_KEY) || "[]")); }
  catch { return new Set(); }
}

function savePortfolio(set) {
  localStorage.setItem(PORTFOLIO_KEY, JSON.stringify([...set]));
}

let portfolioSkills = loadPortfolio();

function toggleSkill(skill) {
  if (portfolioSkills.has(skill)) {
    portfolioSkills.delete(skill);
  } else {
    portfolioSkills.add(skill);
  }
  savePortfolio(portfolioSkills);
  renderPortfolio();
}

function togglePortfolio() {
  const body = document.getElementById("portfolio-body");
  body.classList.toggle("open");
  document.getElementById("portfolio-toggle").textContent =
    body.classList.contains("open") ? "⊖ My Portfolio" : "⊕ My Portfolio";
}

```

- [ ] **Step 2: Add `buildPicker()` function**

Find:
```javascript
// ── Ticker tape ──────────────────────────────────────────────────────────────
```

Insert BEFORE it:
```javascript
// ── Portfolio ─────────────────────────────────────────────────────────────────
function buildPicker() {
  const container = document.getElementById("skill-picker");
  const skills = Object.keys(INDEX.skills).sort();
  container.innerHTML = skills.map(skill => {
    const sel = portfolioSkills.has(skill) ? " selected" : "";
    return `<button class="pick-chip${sel}" onclick="toggleSkill('${skill}')">${skill}</button>`;
  }).join("");
}

function renderPortfolio() {
  buildPicker();

  const tbody = document.getElementById("portfolio-rows");
  const empty = document.getElementById("portfolio-empty");
  const selected = [...portfolioSkills].filter(s => INDEX.skills[s]);

  if (selected.length === 0) {
    tbody.innerHTML = "";
    empty.style.display = "block";
    document.getElementById("gap-list").innerHTML = "";
    return;
  }
  empty.style.display = "none";

  // Sort by latest price descending
  selected.sort((a, b) => {
    const pa = latestPoint(a)?.price ?? 0;
    const pb = latestPoint(b)?.price ?? 0;
    return pb - pa;
  });

  tbody.innerHTML = selected.map(skill => {
    const pt = latestPoint(skill);
    const { text, cls } = fmtMom(pt?.mom_pct);
    const sat = INDEX.skills[skill].latest_saturation;
    return `<tr onclick="openModal('${skill}')" style="cursor:pointer">
      <td><strong>${skill}</strong></td>
      <td>${fmtPrice(pt?.price)}</td>
      <td class="skill-mom ${cls}">${text}</td>
      <td>${satDot(sat)}</td>
      <td>${pt?.count?.toLocaleString() ?? "—"}</td>
    </tr>`;
  }).join("");

  renderGaps(selected);
}

function renderGaps(held) {
  const heldSet = new Set(held);
  // Hot skills not in portfolio: top 5 by price that user doesn't hold
  const allSkills = Object.keys(INDEX.skills);
  const notHeld = allSkills
    .filter(s => !heldSet.has(s))
    .map(s => ({ skill: s, price: latestPoint(s)?.price ?? 0 }))
    .sort((a, b) => b.price - a.price)
    .slice(0, 6);

  if (notHeld.length === 0) {
    document.getElementById("gap-list").innerHTML = "";
    return;
  }

  document.getElementById("gap-list").innerHTML = `
    <h3>Top skills not in your portfolio</h3>
    ${notHeld.map(({ skill, price }) =>
      `<span class="gap-chip" onclick="toggleSkill('${skill}')" title="Add ${skill} (price: ${fmtPrice(price)})">${skill} +</span>`
    ).join("")}`;
}

```

- [ ] **Step 3: Wire into page init**

Find in `public/index.html` the DOMContentLoaded / init block. It will look like:
```javascript
  buildTicker();
  buildMovers();
  buildTable();
```

Add `buildPicker();` and `renderPortfolio();` after those three lines:
```javascript
  buildTicker();
  buildMovers();
  buildTable();
  buildPicker();
  renderPortfolio();
```

- [ ] **Step 4: Commit**

```bash
git add public/index.html
git commit -m "feat: portfolio skill picker and holdings table with localStorage"
```

---

## Task 4: Open portfolio on load if skills saved, auto-open on first chip click

**Files:**
- Modify: `public/index.html`

- [ ] **Step 1: Auto-open portfolio panel if user has saved skills**

Find the init block (same location as Task 3 Step 3). Add after `renderPortfolio();`:
```javascript
  if (portfolioSkills.size > 0) {
    document.getElementById("portfolio-body").classList.add("open");
    document.getElementById("portfolio-toggle").textContent = "⊖ My Portfolio";
  }
```

- [ ] **Step 2: Auto-open panel on first chip click**

Find the `toggleSkill` function added in Task 3:
```javascript
function toggleSkill(skill) {
  if (portfolioSkills.has(skill)) {
    portfolioSkills.delete(skill);
  } else {
    portfolioSkills.add(skill);
  }
  savePortfolio(portfolioSkills);
  renderPortfolio();
}
```

Replace with:
```javascript
function toggleSkill(skill) {
  if (portfolioSkills.has(skill)) {
    portfolioSkills.delete(skill);
  } else {
    portfolioSkills.add(skill);
    // Auto-open the panel on first selection
    const body = document.getElementById("portfolio-body");
    if (!body.classList.contains("open")) {
      body.classList.add("open");
      document.getElementById("portfolio-toggle").textContent = "⊖ My Portfolio";
    }
  }
  savePortfolio(portfolioSkills);
  renderPortfolio();
}
```

- [ ] **Step 3: Push and verify on Netlify**

```bash
git add public/index.html
git commit -m "feat: auto-open portfolio panel on first skill selection"
git push
```

Open the Netlify URL. Verify:
- Clicking "⊕ My Portfolio" expands the panel
- Clicking skill chips toggles them green (selected state)
- Holdings table populates with selected skills
- "Top skills not in portfolio" shows gap chips
- Refreshing the page restores the selection from localStorage
- Clicking a row in the holdings table opens the skill modal

---

## Self-Review

**Spec coverage:**
- ✅ Netlify deploy config (Task 1)
- ✅ GitHub secrets (Task 1)
- ✅ Portfolio panel HTML + CSS (Task 2)
- ✅ Skill picker chips with localStorage (Task 3)
- ✅ Holdings table: price, momentum, saturation, count (Task 3)
- ✅ Gap analysis: top skills not in portfolio (Task 3)
- ✅ Auto-open on saved state + first click (Task 4)

**Placeholder scan:** None found — all steps have actual code.

**Type consistency:**
- `portfolioSkills` — `Set<string>` throughout, consistent
- `latestPoint(skill)` — existing utility, returns `{price, mom_pct, count, saturation}` or null
- `fmtMom`, `fmtPrice`, `satDot` — all existing utilities, consistent call signatures
- `renderPortfolio()` called from `toggleSkill()`, init block, and `togglePortfolio()` — consistent
