# Interpreting Black Swans & Boltzmann with a Thermodynamic Bias

**Revised and extended with eight months of evidence from a live system (RedHood Systems)** — Version 3, October 2026. Tazeem Chowdhury, Research, Redhood Capital, Canada. Supersedes SSRN 4315813 (v1, Dec 2022) and SSRN 5111819 (v2, Jan 2025).

_Markdown reference copy of the LaTeX manuscript (`paper/main.tex` → `paper/main.pdf` in the RedHood Systems repository); figures and the ledger table are in the PDF._

## Abstract

The second law of thermodynamics says that the entropy of the universe does not decrease; living systems nevertheless build order locally by exporting disorder, and nature expresses the resulting robustness as redundancy. Earlier versions of this paper transported that picture to financial markets through three constructs: a Boltzmann-type return distribution with fat tails, a market entropy that distinguishes ordinary from tail states, and Ed Seykota's notion of portfolio *heat*, combined into temperature- and entropy-adjusted position sizing and a four-regime taxonomy. This version confronts the framework with its own implementation. Between February and October 2026 the author ran RedHood Systems, a pipeline that aggregates 2,930 feed items from ten sources, asks a large language model to extract 188 market narratives with a 1–10 "entropy-risk" score, stress-tests each narrative with an adversarial pass, grades the resulting hypotheses, and gates them with a thermodynamic regime detector. Instrumenting that system exposed four defects in the framework as deployed: a units mismatch that pinned every position at its cap; an entropy threshold that no histogram of ten bins can exceed, so that the crisis and transition regimes were unreachable; a drift alarm whose threshold lies below the small-sample bias of the Kullback–Leibler estimator, so that it fired on every report; and a heat budget that was displayed but never measured. Deeper than the defects, the entropy of a range-adaptive histogram *falls* during crashes because one tail event stretches the bin width, which is the opposite of the construct's intent. We replace it with the entropy of fixed energy levels in units of the base temperature, derive the equilibrium occupation entropy as a function of T/T_base, calibrate the drift statistic by Monte Carlo, and restate the regime taxonomy so that each label is reachable and its meaning is explicit: "crisis" is temperature sustained far enough above base that the occupation has spread, not an independent measurement of disorder. On SPY from October 2024 to October 2026 the corrected detector labels 44 days of the April 2025 tariff shock as crisis, where the deployed detector could only say "choppy". Closing the profit-and-loss loop that the system never ran shows that the long side of its narratives lagged SPY by 7.6% over 60 trading days in a market that rose 12%. An apparent redundancy effect—repeated mentions of a ticker doing worse than first mentions—does not survive controls: the losses belong to two themes, defence and gold, that were both the most repeated and the worst performers, and outside them repeated mentions did no worse than first ones. The framework survives with its entropy redefined, its thresholds calibrated, its heat made endogenous, and its empirical claims cut to what one eight-month sample supports.


*Imitation is the sincerest form of flattery that mediocrity can pay to greatness. — Oscar Wilde*



**Keywords:** market thermodynamics; entropy estimation; regime detection; system heat; large language models; narrative risk; algorithmic trading

**What changed since Version 2.** Equation (3) had a sign error in its tail term; it is corrected and re-derived from the chain rule for entropy (§2.2, Appendix 10). The modified Boltzmann density of Equation (2) was not integrable and, once regularised, has exponential tails; it is replaced by a piecewise Laplace-core, Pareto-tail form and tested against Gaussian, Laplace and Student-$t$ alternatives (§2.1). The illustrative performance table and the empty regime figure of Version 2 are withdrawn and replaced by measured results (§§4–6). Appendix C’s trading rules, garbled in typesetting, are restored and revised. The template text in the declaration of interest is replaced by an actual declaration (§9). Everything in §§3–6 is new. An independent numerical check of a draft of this version, performed by a model instance that had not seen the analysis, is acknowledged in §9; its findings reshaped §2.4, §5 and §6.3.

# Context and motivation

Financial markets resemble thermodynamic systems in the ways that matter for risk: they are made of many interacting agents, they exhibit emergent regularities that no agent intends, and their extreme states are governed by tails that averages do not describe. Version 1 of this paper began from Epictetus and Taleb : the tails are where Lady Fortuna does her work, and they are “not typically measurable, predictable or modellable” with the tools of the Gaussian world. Version 2 turned that observation into a framework: a Boltzmann-type distribution for returns with a temperature (volatility) and a tail exponent; a market entropy; energy functions for volatility and trend; position sizing that scales as $(T_{\mathrm{base}}/T)^2$, decays in entropy and in portfolio heat; and a four-regime taxonomy in temperature–entropy space.

What Version 2 lacked was contact with data. Its “performance” table was illustrative, its regime figure contained no observations, and its code listings had never run against a market. This version supplies the missing contact. From February to October 2026 the author built and operated RedHood Systems, an open-source pipeline[^2] that aggregates market commentary, asks a large language model (LLM) to extract the dominant narratives and to score each one’s *entropy risk*, stress-tests the narratives adversarially, grades the resulting trade hypotheses, extracts their tickers, and gates them through a thermodynamic regime detector implemented directly from Version 2. The system wrote every intermediate quantity to a database. Reading that database back is the empirical core of this paper.

The findings fall into three groups. First, *most of the framework as deployed was inert*: a units mismatch, an unreachable entropy threshold, an uncalibrated drift alarm and an unmeasured heat budget meant that only the temperature factor had any effect on what the system did. These are implementation defects, but they are instructive because each one points at an ambiguity in the theory. Second, *the entropy construct itself was mis-specified*: a histogram whose bins adapt to the sample range measures how concentrated the returns are relative to their own extremes, so a crash lowers it. The physical analogy, taken seriously, dictates the fix: fix the energy levels and let temperature determine their occupation. Third, *the narrative layer, once its profit-and-loss loop is closed, is a lesson in concentration rather than in redundancy*: the long side of the narratives lagged the index, the losses sit in two themes that the feed repeated most, and the redundancy effect the original abstract anticipated cannot be separated from those themes in a sample of one bull-market spring.

The paper is organised as follows. Section 2 restates the theoretical framework with the corrections. Section 3 describes RedHood Systems as an instrument. Section 4 reports what instrumenting the deployed framework revealed, and Section 5 the corrected estimators and detector, tested on two years of SPY. Section 6 reports the narrative layer and the closed ledger with its robustness checks. Section 7 discusses what the evidence does and does not support, and Section 8 concludes. Appendices give derivations, the reference implementation, the restored trading rules, and reproducibility notes.

# Theoretical framework, revised

## Boltzmann core, power-law tail

The Boltzmann distribution gives the probability that a system in thermal equilibrium occupies a state of energy $E$: $$P(E)=\frac{1}{Z}e^{-E/kT}. \label{eq:boltzmann}$$ Version 2 proposed, for daily returns $r$ with volatility (temperature) $\sigma$ and tail exponent $\alpha$, the modification $P(r)\propto e^{-|r|/\sigma}|r|^{-\alpha}$. That expression fails twice. It is not a density, because $|r|^{-\alpha}$ is not integrable at the origin for $\alpha\ge1$; and even when regularised to $e^{-|r|/\sigma}(1+|r|/r_0)^{-\alpha}$ it cannot have a fat tail, because the exponential factor dominates for any finite $\sigma$ and the power-law factor can only *thin* what it multiplies. Fitted by maximum likelihood to SPY returns the regularised form confirms this by running $\sigma$ to its bound, i.e. by deleting the Boltzmann factor (Table [tab:fits]). The intent—an exponential core at a scale set by temperature, crossing over to a power-law tail—requires the exponential to switch off beyond a crossover scale $r_0$: $$P(r)=\frac{1}{Z}\begin{cases} e^{-|r-\mu|/\sigma}, & |r-\mu|\le r_0,\\[2pt] e^{-r_0/\sigma}\left(\dfrac{r_0}{|r-\mu|}\right)^{1+\alpha}, & |r-\mu|>r_0,\end{cases}\qquad Z=2\left[\sigma\left(1-e^{-r_0/\sigma}\right)+e^{-r_0/\sigma}\frac{r_0}{\alpha}\right], \label{eq:bp}$$ which is continuous at $r_0$, integrable for every $\alpha>0$, and has tail exponent $\alpha$ in the sense that $P(|r-\mu|>x)\sim x^{-\alpha}$. Section 5 tests it. On 500 daily SPY log returns the Laplace core alone improves on the Gaussian by $\Delta\mathrm{AIC}\approx152$; the piecewise form [eq:bp] improves on the Laplace by a further $14$; and a Student-$t$ with $\nu\approx3.1$ degrees of freedom, with one parameter fewer, improves on [eq:bp] by $9$. We therefore keep [eq:bp] as the statement of the two scales a return distribution has, and use the Student-$t$ as the working density. Its tail exponent is $\nu$, and $\nu\approx3$ is the “cubic law” documented across markets by and part of the stylised facts catalogued by and ; the Hill estimates reported below (2.4–2.8) agree.

## Market entropy: fixed levels, not adaptive bins

Version 2 defined the market entropy as $S=-k\sum_i p_i\ln p_i+\beta\sum_j q_j\ln q_j$ with $p_i$ the probabilities of ordinary states and $q_j$ those of tail events. The second term is signed wrongly: since $\ln q_j<0$, it *reduces* the entropy as tail events become more probable. The construct the sentence describes is the entropy of a two-component mixture, and the chain rule for entropy gives its exact form. Let $\pi$ be the total tail mass, $p$ the conditional distribution over ordinary states and $q$ the conditional distribution over tail states. Then $$S_{\mathrm{market}}=h(\pi)+(1-\pi)\,H(p)+\pi\,H(q),\qquad h(\pi)=-\pi\ln\pi-(1-\pi)\ln(1-\pi), \label{eq:mixture}$$ with $H(\cdot)=-\sum(\cdot)\ln(\cdot)$ (Appendix 10). Every term is non-negative; the weight on the tail term is the tail mass itself, so the free parameter $\beta$ of Version 2 is not needed. The binary term $h(\pi)$ is the part of the disorder that lives in *whether* a day is a tail day; it rises with $\pi$ until $\pi=1/2$.

The deeper problem is how $p$ and $q$ are estimated. Both implementations derived from Version 2 (Listing 4 there, and the Python and PowerShell modules of RedHood Systems) compute a Shannon entropy over an equal-width histogram whose edges are the sample minimum and maximum. Such an estimator measures how concentrated the sample is *relative to its own range*. A single crash day widens the range, pushes the other observations into one or two bins, and *lowers* the entropy. Section 4 shows this happening on SPY in April 2025, and over the two-year sample the correlation between the 20-day temperature and this entropy was $-0.47$ ($-0.51$ on the 441 days for which a 60-day comparison series also exists). An entropy that falls in a crisis cannot define a crisis regime.

The thermodynamic analogy, taken literally, dictates the alternative. In [eq:boltzmann] the energy levels are fixed by the system and the temperature determines how they are occupied—the maximum-entropy occupation given the mean energy, in Jaynes’s reading ; at low temperature only the lowest levels are populated (low entropy), at high temperature the population spreads upward (high entropy). The market analogue is to fix the levels as standardised return intervals in units of the base temperature. With daily scale $\sigma_b=T_{\mathrm{base}}/\sqrt{252}$ and $z=r/\sigma_b$, we use the ten levels $$\mathcal{L}=\{(-\infty,-3],(-3,-2],(-2,-1],(-1,-\tfrac12],(-\tfrac12,0],(0,\tfrac12],(\tfrac12,1],(1,2],(2,3],(3,\infty)\} \label{eq:levels}$$ and define the *occupation entropy* of a window of $N$ returns as the plug-in Shannon entropy of the level frequencies with the Miller–Madow correction , $$\hat S=-\sum_{\ell\in\mathcal L}\hat p_\ell\ln\hat p_\ell+\frac{k-1}{2N},\qquad \eta=\hat S/\ln k, \label{eq:occ}$$ where $k=10$ and $\eta\in[0,1]$ is the normalised disorder ratio. Because the levels are fixed, $\hat S$ has an equilibrium value at every temperature. If returns are Laplace with standard deviation $\sigma$, the level masses are differences of the Laplace distribution function with scale $b=\sigma/\sqrt2$ evaluated at the edges of [eq:levels], and the equilibrium entropy $S_{\mathrm{eq}}(T/T_{\mathrm{base}})$ follows by substitution: $S_{\mathrm{eq}}=1.70$ at $T/T_{\mathrm{base}}=0.75$, $1.90$ at $1$, $2.13$ at $1.5$ and $2.24$ at $2$ (the ceiling is $\ln10=2.30$). High entropy is defined *relative to the band that is normal at the base temperature*: a window is spread if $\hat S$ exceeds the 95th percentile of $\hat S$ under the Laplace null at $T=T_{\mathrm{base}}$, which the shipped calibration puts at $2.034$ nats for $N=60$. With this estimator the correlation between temperature and entropy on SPY is $+0.91$ when both use a 60-day window and $+0.57$ against the 20-day temperature the detector uses, and the crisis quadrant is populated (§5).

## Energy functions

We keep the decomposition of Version 2 with explicit units. Total market energy over a window is $$E_{\mathrm{total}}=E_{\mathrm{kin}}+E_{\mathrm{pot}},\qquad E_{\mathrm{kin}}=\tfrac12\sigma^2,\qquad E_{\mathrm{pot}}=\sum_{i}w_i\ln\frac{P_i}{P_{i-1}}, \label{eq:energy}$$ with $\sigma$ the annualised volatility (temperature) and $E_{\mathrm{pot}}$ the weighted cumulative log return (trend energy) with weights $w_i$ summing to one. Kinetic energy is what the sizing kernel of §2.5 dissipates; potential energy is what the entry rules of Appendix 12 try to harvest. Both are stated in units of (annualised) squared return and of log return respectively, so that thresholds can be written as dimensionless ratios.

## Regimes: temperature, occupation and departure

Version 2 classified regimes by temperature and entropy: trending (low $T$, low $S$), choppy (high $T$, low $S$), crisis (high $T$, high $S$), transition (low $T$, high $S$). With the occupation entropy of [eq:occ] the construction is well defined, but it has a property that must be stated plainly: in equilibrium $\hat S$ is a monotone function of $T$ (the curve $S_{\mathrm{eq}}$ above), so “$\hat S$ above the base band” is not an independent measurement of disorder. It is the statement that the temperature has been far enough above base, for long enough, that the 60-day occupation has spread; the equilibrium curve crosses the 2.034-nat band at $T/T_{\mathrm{base}}=1.25$. A *crisis* in this taxonomy is therefore a sustained-temperature criterion, distinguished from a one-day spike (which raises the 20-day temperature but not the 60-day occupation) rather than from a hot-but-orderly market. We keep it because that is what Version 2’s “high $T$, high $S$” meant operationally, and because the distinction between a spike and a sustained hot regime is the one the sizing rules need.

A second coordinate that is *not* monotone in temperature is the departure of the observed occupation from the Boltzmann occupation *at the current temperature*, measured by the Kullback–Leibler divergence : $$D=D_{\mathrm{KL}}(\hat p\,\|\,p_T)=\sum_{j}\hat p_j\ln\frac{\hat p_j}{p_{T,j}},\qquad p_{T,j}=\frac{F_{b}(u_j)-F_{b}(u_{j-1})}{\sum_{j'}\left[F_{b}(u_{j'})-F_{b}(u_{j'-1})\right]},\quad b=\hat\sigma/\sqrt2, \label{eq:kl}$$ where $F_b$ is the Laplace distribution function and $u_j$ are the edges of $k=\lfloor\sqrt N\rfloor$ equal-width bins over the window’s range, with the reference mass renormalised over the same range. This is a goodness-of-fit statistic for the shape of the occupation, so range-adaptive bins are appropriate here even though they are not for the entropy; it is the “Gibbs lemma” statistic that the deployed detector already computed, with two corrections: the reference is integrated over the bins rather than evaluated at their centres, and its scale is $\hat\sigma/\sqrt2$ rather than $\hat\sigma$ (the Laplace scale parameter is not its standard deviation). On SPY the correlation between $D$ and the temperature is $-0.04$. The taxonomy, as implemented in the shipped detector, is

| Label                                     | Temperature              | Occupation / shape        | Action                                   |
|:------------------------------------------|:-------------------------|:--------------------------|:-----------------------------------------|
| <span class="smallcaps">trending</span>   | $T\le T_{\mathrm{base}}$ | $D$ within null band      | amplify, up to $(T_{\mathrm{base}}/T)^2$ |
| <span class="smallcaps">transition</span> | $T\le T_{\mathrm{base}}$ | $D$ above null band       | neutral; never amplify                   |
| <span class="smallcaps">choppy</span>     | $T>T_{\mathrm{base}}$    | $\hat S$ within base band | reduce by $(T_{\mathrm{base}}/T)^2$      |
| <span class="smallcaps">crisis</span>     | $T>T_{\mathrm{base}}$    | $\hat S$ above base band  | no new entries                           |



Both bands are quantiles of the Laplace null obtained by simulation (§5). The departure statistic is a slow variable whose power against realistic alternatives is modest, which we report rather than hide; it is also the only one of the three coordinates that does not move with temperature.

## Position sizing and heat

The sizing kernel of Version 2 is retained, with units declared. All temperatures are annualised volatilities expressed as decimals ($T_{\mathrm{base}}=0.15$ means 15%). For equity $Q$, base risk fraction $f_0=0.01$, portfolio heat $h$ (the fraction of equity that would be lost if every open stop were hit) and heat capacity $h_{\max}$, $$\text{size}=Q\,f_0\;\min\!\left\{\left(\frac{T_{\mathrm{base}}}{T}\right)^{2},\,c\right\}\;e^{-(\eta-\eta_{\mathrm{eq}})/\lambda}\;\left(1-\frac{h}{h_{\max}}\right), \label{eq:size}$$ capped at $2\%$ of equity, with $c=2.5$, $\lambda=0.5$, and $\eta_{\mathrm{eq}}$ the equilibrium disorder ratio at the current temperature; the size is zero in <span class="smallcaps">crisis</span> and never above the base size in <span class="smallcaps">transition</span>. Two things changed. The entropy factor is measured relative to equilibrium, so that a hot but orderly market is not penalised twice; and the heat term is computed from the open book, not supplied as a constant. Seykota’s heat is the sum over open positions of the loss at stop divided by equity, a one-number stand-in for the covariance budget of ; Section 6 shows that, had it been computed, it would have been the binding constraint on the system for most of March 2026.

# RedHood Systems as an instrument

RedHood Systems is a Python/PowerShell pipeline run on a schedule by the author. Each run: (i) collects recent items from X/Twitter accounts via RSS proxies, Substack newsletters and a read-only newsletter inbox; (ii) balances the items across authors so that no single high-frequency account dominates the prompt; (iii) sends up to fifty items to an LLM (Claude; the model version was upgraded once during the period) with the instruction to act as “a portfolio manager with a physics PhD”, extract the top narratives, and score each one’s *entropy risk* on a 1–10 scale where low means stable consensus and high means conflicting information; (iv) runs a second, adversarial LLM pass that writes the strongest bear case for each narrative, lists disconfirming signals, and issues a sizing verdict—Full, Half, Quarter or Pass; (v) grades each trade hypothesis 0–20 on specificity, catalyst, risk management and cohesion with a deterministic rubric and extracts the long-side tickers; (vi) computes the market regime from recent SPY closes with the detector of Version 2; and (vii) writes a styled report and persists everything to a star-schema SQLite database. A separate PowerShell module computes per-symbol temperature, entropy, momentum and RSI and emits IN/OUT/NEUTRAL recommendations with thermodynamic position sizes.

Two features make the pipeline an instrument rather than a product. Every quantity the framework names—temperature, entropy, KL divergence, signal multiplier, heat budget, entropy risk, conviction—is written down at every run, so the framework can be audited against itself. And the two LLM passes implement, in a loose but useful sense, the forward and time-reversed trajectories of a fluctuation theorem : the first pass constructs the path by which a narrative produces a trade, the second constructs the path by which the same narrative destroys it, and the sizing verdict is the log-ratio of their plausibilities as judged by the model. We do not push the analogy further than that, but it explains why the adversarial pass exists.

#### Data.

Between 22 February and 22 October 2026 the system completed 51 runs with look-back windows from five minutes to 125 hours (median 5.5 hours), collecting 2,930 feed items from ten sources and extracting 188 narratives: the first two runs returned one narrative each, one run returned none, 27 returned three, and the 21 runs from 26 March returned five. The feed is concentrated: three accounts supplied 55% of all items and five supplied 83%, which is why author balancing was introduced. Narratives referenced 545 (narrative, ticker, side) triples over 202 distinct tickers: 382 long, 161 short, two hedges. Forty-five regime reports (27 distinct timestamps) and 36 PowerShell sizing snapshots (105 symbol-rows) were archived. The grading and profit-and-loss steps had been built but never run; the price table of the database was empty when this analysis began.

# What instrumenting the deployed framework revealed

Reading the database back exposed four defects. Each is an implementation error, and each traces to an ambiguity in Version 2.

#### L1. Units: the sizer never left its cap.

The PowerShell sizer computes temperature as $\mathrm{std}(r)\sqrt{252}$ from decimal returns (so $T\approx0.36$ for a 36% stock) but was configured with $T_{\mathrm{base}}=25$, inherited from Version 2’s Listing 1, which set `base_temp=15` without specifying the units of the returns it was applied to. The ratio $(T_{\mathrm{base}}/T)^2$ was therefore of order $10^3$–$10^4$, and all 49 symbol-rows in the eight snapshots after the June 2026 data fix reported a position size exactly at the 2% cap (\$2,000 on \$100,000) and a temperature status of “LOW”. The thermodynamic kernel was present in the code and absent from the output. The fix is notational—state $T_{\mathrm{base}}$ as a decimal—but the lesson is that every quantity in [eq:size] must be dimensionless before a threshold touches it.

#### L2. An entropy threshold that no histogram can exceed.

The Python regime detector estimated entropy from a 20-return histogram with ten bins and declared “high entropy” when $\hat S>S_{\mathrm{base}}=2.5$ nats. The entropy of ten bins cannot exceed $\ln10=2.303$. Across the 27 live reports the entropy ranged from 1.78 to 2.16; across the 481 trading days of our SPY reconstruction it ranged from 1.33 to 2.22 (Figure 1c). The crisis and transition regimes were unreachable by construction, and the entropy factor in the signal multiplier, defined as $e^{-(\hat S-S_{\mathrm{base}})/2}$ for $\hat S>S_{\mathrm{base}}$ and $1$ otherwise, was identically one. The detector was a temperature detector. Version 2 is responsible: it gave $S_{\mathrm{base}}$ no definition and its Listing 4 used fifty bins, which has a different ceiling ($\ln50=3.91$) and, on short windows, a different bias. The PowerShell module had already met this problem from the other side—fifty bins on thin intraday samples inflated the entropy and forced an “OUT” recommendation on 56 of 56 symbol-rows between February and June 2026—and was patched in June to use $\lfloor\sqrt N\rfloor$ bins and to report $\eta=\hat S/\ln k$. After the patch the entropy gate produced “OUT” on 5 of 49 rows and the price filter on 39; the combined recommendation was “OUT” on 40. The two modules, written months apart from the same paper, reported entropy on incompatible scales: nats near 2 in one, a 0–1 ratio near 0.7 in the other.

#### L3. A drift alarm below the estimator’s own bias.

The detector’s early-warning statistic was $D_{\mathrm{KL}}(\hat p\|p_{\mathrm{Boltzmann}})$ with fifteen bins on twenty returns and an alert at 0.25 nats. The plug-in KL divergence, like the plug-in entropy, is biased upward by approximately $(k-1)/2N$ , which for $k=15$, $N=20$ is $0.35$ nats—above the alert. Figure 2b shows the statistic’s distribution when the data are *exactly* Laplace: 92% of null samples exceed 0.25. Two further misspecifications push in the same direction: the reference density was evaluated at bin centres rather than integrated over bins, and its scale was set to $\hat\sigma$ instead of the Laplace scale $\hat\sigma/\sqrt2$. In the live reports the statistic ranged from 0.26 to 0.75 and the “REGIME DRIFT” warning was displayed in 27 of 27; on the two-year SPY reconstruction it fired on 97.5% of days. An alarm that is always on carries no information.

#### L4. A heat budget that was displayed but never measured.

Every live report showed “Heat budget: 100% remaining”. The detector’s heat was an input that no caller ever set, and the PowerShell sizer passed a constant zero. Portfolio heat, the construct the paper took from Seykota, was therefore never computed. Section 6 computes it after the fact from the narrative flow and finds that it would have exceeded any plausible capacity for most of March 2026.

#### The construct-level problem.

Beneath L2 lies the problem identified in §2.2. Figure 1c overlays the deployed entropy and the fixed-lattice entropy of [eq:occ] on the same SPY returns. On 2 April 2025, the eve of the tariff shock, the deployed 20-day entropy stood at 1.97 nats with the temperature at 20%; by 11 April, after SPY had fallen 10.5% in two sessions, the temperature had risen to 51% and the deployed entropy had *fallen* to 1.39, its two-year minimum, while the fixed-lattice entropy rose from 1.97 to 2.13 and went on to 2.26 by mid-May. Over the common sample the deployed estimator is correlated with the 20-day temperature at $-0.51$, the fixed-lattice estimator with the 60-day temperature at $+0.91$. The deployed detector, with its crisis state unreachable, labelled all 44 days that the corrected detector calls crisis “choppy” (Figure 1d).

SPY, 23 October 2024 to 22 October 2026. (a) Close. (b) Annualised realised volatility over 20 and 60 days; the dashed line is Tbase = 15%, the 75th percentile of the 20-day series. (c) Entropy of the same returns under the deployed estimator (range-adaptive bins, k = 10, N = 20) and under the fixed-level estimator of Eq. [eq:occ] (k = 10 levels in units of Tbase, N = 60, Miller–Madow corrected). The deployed threshold of 2.5 nats lies above the ceiling ln 10. (d) Regime labels from the deployed detector (in effect a temperature detector) and from the shipped v2 detector of §5. The dashed vertical line marks the start of the RedHood live period.

# Corrected estimators and a calibrated detector

## Calibrating by simulation

All thresholds in the corrected detector are quantiles of the statistic’s distribution under a Laplace null at the base temperature, obtained by Monte Carlo. The shipped detector simulates 4,000 windows of $N=60$ Laplace returns at $T=T_{\mathrm{base}}$ (seed 7) when first instantiated and caches the result; it gives $S_{\mathrm{hi}}=2.034$ nats and $D_{\mathrm{hi}}=0.110$ for $k=\lfloor\sqrt{60}\rfloor=7$ bins. A 20,000-window check gives $2.040$ and $0.113$. Figure 2 summarises the three relevant distributions. The plug-in entropy of ten range-adaptive bins on twenty Laplace returns (20,000 windows) has mean 1.88 and 95th percentile 2.14; the deployed threshold of 2.5 is unattainable. The deployed KL statistic has mean 0.40 under the null and exceeds the alert in 92% of samples. The power of the corrected statistic in the shipped configuration is modest: at $D_{\mathrm{hi}}=0.110$ the probability of an alert when sixty returns are drawn from a variance-matched Student-$t$ with three degrees of freedom is 12.6%, and from a Gaussian 32%. The statistic detects gross departures from exponential occupation, not subtle ones; that is the honest capability of a shape test on three months of daily data.

Monte Carlo null distributions (Laplace returns at T = Tbase). (a) Plug-in entropy of ten bins on twenty returns never reaches the deployed threshold. (b) The deployed KL statistic exceeds its alert in 92% of null samples. (c) The corrected statistic with a bin-integrated reference and the Laplace scale $b=\hat\sigma/\sqrt2$, N = 60, k = 7; the dashed line is the shipped alert Dhi = 0.110.

## Temperature

The 20-day annualised volatility of SPY over the two years had median 12.7%, quartiles 10.3% and 15.0%, and 90th percentile 19.6%; $T_{\mathrm{base}}=15\%$ is therefore the upper-quartile boundary and “hot” means the hottest quarter of days. We keep $T_{\mathrm{base}}=0.15$ as the lattice scale of [eq:levels] and as the sizing base. A 60-day window is used for the occupation entropy and the departure statistic because twenty returns in ten bins cannot support a shape statistic; the temperature itself is computed over 20 days.

## Occupation entropy and the Boltzmann line

Figure 3a tests the occupation picture directly. Standardising the 500 daily returns by their full-sample standard deviation and binning them in half-$\sigma$ levels (with wide outer bins so that every observation is counted), we regress $\ln\hat p$ on the harmonic level energy $E=z^2/2$. Over the core ($|z|\le2$) the fit is a straight line with effective temperature $T_{\mathrm{eff}}=0.68$ ($R^2=0.89$) against a Gaussian’s $1.0$: the core is colder than Gaussian, which is another way of saying it is peaked. The linear-energy (Laplace) fit on the same core has $R^2=0.92$. Beyond the core the Boltzmann line fails completely: the levels at $|z|\approx2.75$ hold four observations against the line’s prediction of about 0.4, and the four April 2025 sessions at $z=-5.8$, $-4.9$, $-4.3$ and $+9.6$ sit at energies where the line predicts no observations at all in a sample of this size. Figure 3b and Table [tab:fits] compare densities: the Student-$t$ with $\nu=3.13$ has the best likelihood and the smallest Kolmogorov–Smirnov distance (0.033 against 0.041 Laplace and 0.102 Gaussian); the piecewise form [eq:bp] beats the Laplace and the tempered Version 2 form but not the $t$, and its fitted crossover sits inside the core ($r_0=0.64\sigma$) with a tail exponent of 1.7, so it is absorbing the shoulders rather than the tail. The Hill estimator of the tail index is 2.84 on the top decile and 2.42 on the top 5% of absolute returns. The empirical probability of a move beyond three standard deviations is 1.0%, which the Laplace matches (1.0%), the $t$ slightly overstates (1.4%) and the Gaussian understates by a factor of four (0.27%). The sample’s excess kurtosis is 20, driven by the April 2025 sessions with log returns of $-6.0\%$, $-5.1\%$ and $+10.0\%$.

(a) Occupation of fixed return levels (half-σ bins, wide outer bins) against harmonic level energy, with the Boltzmann line fitted on |z| ≤ 2; the arrows mark the four April 2025 sessions. (b) Histogram of daily log returns on a logarithmic density scale with the fitted Gaussian, Laplace and Student-t densities.

## Regime labels on two years of SPY

The shipped detector (Appendix 11), run day by day over the 441 classifiable days, gives 291 <span class="smallcaps">trending</span>, 67 <span class="smallcaps">choppy</span>, 44 <span class="smallcaps">crisis</span> and 39 <span class="smallcaps">transition</span>. The crisis days run from 4 April to 9 June 2025, with gaps on days when the 20-day temperature dipped below base while the 60-day occupation remained spread; the deployed detector labelled every one of those 44 days choppy. Transition days come in fourteen episodes of drift, the longest from 2 to 7 July 2025, 17 to 24 July 2025, 30 September to 8 October 2025, 23 to 29 October 2025 and 22 May to 4 June 2026; the alert fires on 9.5% of days against a design rate of 5%. The 22 May–4 June 2026 episode preceded the $-2.6\%$ session of 5 June 2026, the largest fall of the year. One such coincidence is an anecdote, and we report it as one. During the RedHood live period (22 February to 22 October 2026) the labels are 118 trending, 39 choppy and 12 transition; 2026 contained no crisis by this definition. Over the live period the deployed detector, which could only distinguish hot from cold, gave 130 trending and 39 choppy days, so on the temperature axis the two agree; what the corrected detector adds in this period is the twelve transition days and the measured heat.

# Results from the narrative layer and the closed ledger

## The entropy-risk score and the adversarial pass

The LLM’s entropy-risk scores for the 188 narratives had mean 6.65 and standard deviation 1.71; no narrative was scored 1, 2 or 10, seven were scored 3, and 62 (33%) were scored 8 or 9. The model used the scale as a measure of how contested a story was, and most stories it chose to report were contested. The adversarial pass returned a verdict for 166 narratives: 62 Quarter, 58 Half, 46 Pass and *zero* Full Size. Treating the verdicts as multipliers (1, 0.5, 0.25, 0), their Spearman correlation with the entropy-risk score is $\rho_s=-0.33$ ($t=-4.5$, $n=166$): the first pass’s uncertainty score anticipates the second pass’s downgrade (Figure 4b). The share rated Pass rises from 0% at score 3 to 46% at score 8, not monotonically (23% at 4, 14% at 5), and falls to 17% at score 9. The deterministic grader was less informative: 120 narratives graded C, 36 D, 29 B and 3 A$-$, with a mean of 10.95/20, and the risk-management axis averaged 0.85 of 5 because hypotheses rarely stated stops or sizes. The grade correlated with neither the entropy score ($\rho_s=-0.07$) nor the verdict ($0.12$).

(a) Rank–frequency plot of the 545 ticker mentions across 188 narratives; 126 of 202 tickers appear once. (b) Mean sizing multiplier and share of “Pass” verdicts from the adversarial pass, by entropy-risk score.

## Redundancy in the feed

Nature expresses robustness as redundancy; a feed of market commentary expresses something else by it. Figure 4a shows the rank–frequency distribution of ticker mentions, which is Zipf-like : a straight line in log–log coordinates with slope $-0.81$ ($R^2=0.93$), and an exact discrete power-law maximum-likelihood exponent of $2.13\pm0.13$ for tickers mentioned twice or more ($2.24\pm0.18$ for three or more). Of 202 tickers, 126 appeared once and five (VIX, XLE, USO, LMT, RTX) accounted for 22% of all mentions. Behind this is the feed concentration already noted (three accounts, 55% of the items) and the LLM’s tendency, when the inputs repeat, to repeat.

## Closing the profit-and-loss loop

The system was built to track a \$2,500 long position per extracted ticker and never did. We close the loop here with the grader as shipped in version 1.4 of the repository, whose exclusion list was extended with the false positives this exercise found (currency and index codes, bond shorthands, and English words that are also symbols). From the 188 hypotheses it yields 227 long-side (narrative, ticker) pairs over 111 symbols (140 pairs in single-name equities, 87 in ETFs) from 125 narratives in 48 runs on 29 distinct run dates. Entry is the first daily close on or after the run date, except that a run completed after the US close enters at the next session’s close; 110 of the 227 pairs are shifted by this rule. We report forward returns over 5, 20 and 60 trading days and to 22 October 2026, each in excess of SPY over the same window. Prices are unadjusted daily closes; no costs, dividends or financing are applied. Positions overlap heavily in time and in symbol, so three $t$-statistics are computed: the naive one over pairs, one over run-date means (the unit at which the system makes decisions; the table reports this one), and one over calendar-month means, which is the coarsest blocking the sample allows and the most honest about overlapping 60-day windows. SPY returned $+12.0\%$ from the first entry to 22 October.

A pair is a *first mention* when its ticker had not appeared as a long on any strictly earlier run date in this ledger; short-side mentions do not count, and pairs on the same date as the ticker’s first appearance are also first mentions. Themes are fixed symbol lists (defence: LMT, RTX, NOC, GD, LHX, ITA, DFEN, KTOS, AVAV, EUAD; gold: GLD, GDX; energy and semiconductors as listed in Appendix 13); “other” is the remainder.

Table [tab:ledger] reports the results. The long side of a narrative gained nothing against SPY in its first five sessions ($-0.1\%$, hit rate 54%), then lagged: $-1.7\%$ at 20 days, $-7.6\%$ at 60 days (run-date $t=-3.4$, month $t=-2.1$, hit rate 27%), $-4.1\%$ to date. The losses are concentrated. The defence-prime basket (54 pairs across 17 run dates) lagged SPY by $23.6\%$ over 60 days with a 6% hit rate and gold (17 pairs) by $15.7\%$; energy ($+9.8\%$ to date) and semiconductors ($+7.1\%$ at 60 days) gained; “other” was flat. The month rows show the same thing in time: 97 of the 227 pairs entered in March 2026, and their 60-day excess return was $-11.0\%$. By entropy band, the high-entropy narratives’ longs lagged by $19.8\%$ at 60 days—but 54 of their 60 sixty-day pairs entered in February or March and 32 are defence or gold names. The adversarial verdict was not monotone in outcome: the narratives it rated Pass had the worst to-date excess return ($-11.4\%$, $t=-3.3$) but were unremarkable at 20 and 60 days, while Quarter-sized narratives did best to date ($+4.6\%$, not significant). Weighting positions by the verdict, by the regime multiplier, or by both, did not improve the 20-day excess return of the flat ledger ($-1.65\%$ of deployed capital flat; $-2.60\%$ verdict-weighted; $-1.49\%$ regime-weighted; $-2.22\%$ both).

#### The redundancy effect, and why we do not claim it.

The raw split by novelty looks like the result the original abstract anticipated: repeat mentions lagged SPY by $11.3\%$ at 60 days against $4.9\%$ for first mentions, and fourth-or-later mentions by $17.3\%$, with run-date $t$-statistics of $-5.4$ and $-5.5$. Three checks remove it. First, composition: 49 of the 101 repeat pairs are defence or gold, and in those themes first mentions did as badly as repeats (defence: $-22.8\%$ against $-23.9\%$ at 60 days). Second, exclusion: outside defence and gold, repeat mentions did *better* than first mentions at every horizon ($+2.9\%$ against $-0.8\%$ at 20 days; $+6.8\%$ against $+2.5\%$ to date; Figure 5b), and the within-date paired difference at 60 days is $+6.9\%$ ($t=+1.5$). Third, dependence: paired within run date over all themes, the repeat-minus-first difference is $-1.3\%$ at 20 days ($t=-0.6$), $-13.2\%$ at 60 days ($t=-2.0$) and $-10.5\%$ to date ($t=-1.1$); the run-date means of the repeat subset have a lag-one autocorrelation of 0.67 because their 60-day windows overlap, and blocked by month the repeat subset’s $t$ is $-1.2$ at 60 days. The honest statement is that in this sample repetition marked the two themes that fell; it did not predict loss on its own. We keep the redundancy filter of Appendix 12 as a hypothesis for the forward test, with the expectation set by this evidence that it may do nothing.

## Heat, computed after the fact

Figure 5c computes the portfolio heat that the narrative flow would have generated had every long-side pair been taken at \$2,500 on a \$100,000 book with an 8% stop and a 20-session hold. Open positions peaked at 94 on 31 March 2026 (mean 26), notional exposure peaked at 235% of equity, and heat—equity lost if every stop were hit—peaked at 18.8% and averaged 5.2%; notional exceeded equity on 38 days and heat exceeded an illustrative 6% capacity on 63 days, from 23 February to 23 April and again from 25 June to 23 July. Against Seykota’s typical capacities of a few per cent, the heat term in [eq:size] would have been the binding constraint through the March flow—which, Table [tab:ledger] shows, was the flow that lost money. The constraint the system displayed as “100% remaining” was the one it most needed.

(a) Mean excess return over SPY of the long side of narratives, first against repeat mentions, all pairs. (b) The same excluding the defence and gold themes. (c) Portfolio heat implied by the narrative flow ($100,000 equity, $2,500 per pair, 8% stop, 20-session hold); the dashed line is an illustrative 6% capacity.

# Discussion

#### What the thermodynamic bias now means.

Version 2 used thermodynamics as a vocabulary. The evidence lets us say what the vocabulary buys. *Temperature* is realised volatility and needs no analogy, but the analogy fixes its units and its base. *Entropy* is useful only when the levels are fixed, and then it is a monotone companion of temperature in equilibrium; the informative quantity is its departure from the equilibrium curve, which is the statistic of [eq:kl], and that statistic is weak. *Free energy*, which Version 1 invoked without using, has a natural reading in the ledger—a narrative that has not yet moved prices carries free energy, and a repeated narrative has dissipated it into price; this is the efficient-markets intuition stated in the vocabulary of the paper—but the ledger does not yet show it: what it shows is that two themes fell, and that the feed repeated them. *Heat* is Seykota’s constraint and it binds first.

#### What the evidence supports, and what it does not.

It supports three claims at the level of this sample: that the entropy and heat factors of Version 2, implemented as written, did nothing, while the temperature factor moved the live multiplier between $0.57\times$ and $2.33\times$; that fixing the levels makes entropy behave as the taxonomy requires, at the cost of making “crisis” a sustained-temperature criterion; and that the long side of the narratives lagged the index over one to three months, with the loss concentrated in defence and gold. It does not support claims about profitability, about the redundancy effect, or about the regime multiplier, which did not help because the live period contained no crisis to avoid. The entropy-risk score and the adversarial verdict carry information about each other and some about outcomes, but neither is a filter that would have made the ledger profitable. The ledger covers eight months of one bull market, 97 of its 227 pairs enter in March 2026, one theme supplies the largest losses, the ticker extractor is heuristic, and the horizons overlap; the month-level $t$-statistics are the ones to believe.

#### Why the defects matter for the theory.

L1–L4 were not typographical. Each marks a place where Version 2 named a quantity without fixing its scale: a base temperature without units, a base entropy without a ceiling, a divergence threshold without a null distribution, a heat capacity without a heat. The corrected framework states every threshold as a quantile of a null distribution or as a dimensionless ratio, and that is the methodological content of this revision.

# Conclusion and further work

The framework of Version 2 was deployed, audited against its own records, corrected, and tested. The corrections are: a return density with a Laplace core and a genuinely power-law tail, with the Student-$t$ as the working choice; a market entropy defined on fixed energy levels with a derived equilibrium curve; a departure statistic with a Monte-Carlo-calibrated threshold and an honest power; a regime taxonomy in which every label is reachable and its meaning stated; and a sizing kernel with declared units and an endogenous heat term. The empirical result is that the narratives’ long side lagged the market and that the loss was concentrated in the themes the feed repeated most; whether repetition itself carries information is left open.

Further work is specified so that it can be falsified. First, a pre-registered forward test: the ledger will be run live from 1 November 2026 with the rule “do not add to a long after its second mention” and the flat ledger as control, and the two will be reported after 120 sessions regardless of outcome, with the expectation, set by this sample, that the rule may do nothing. Second, the regime detector of Appendix 11 is now the one the repository runs; every run persists its state, and the heat term is computed from the ledger. Third, the heuristic grader will be replaced by an LLM grader with the same rubric, and the two scored against the ledger. Fourth, feed concentration will be reduced and the theme and novelty breakdowns re-estimated, since part of what the ledger shows may be the echo of a few accounts rather than of the market. Fifth, transaction costs and a multi-asset extension will be added once the ledger is live.

# Research integrity

#### Declaration of interest.

The author operates Redhood Capital and RedHood Systems as an independent research activity, publishes the RedHood Reads newsletter, and has traded securities mentioned in this paper. No external funding was received. No position was taken on the basis of the results reported here before they were computed. The author is employed outside the financial industry; the views are the author’s own.

#### Use of language models.

The narrative extraction, entropy-risk scoring and adversarial stress-test described in §3 were performed by a commercial LLM as part of the system under study. A language-model assistant was also used in drafting and in computing the analyses of this revision, and a second, independent model instance that had not seen the analysis was asked to check every number, equation and claim of the draft against the archived outputs; its report identified the overstated redundancy result, the inconsistency in the regime taxonomy, the tail behaviour of the regularised Version 2 density, and the omitted observations in the occupation figure, all of which were corrected before this version. All analyses were re-run from the raw records and the author is responsible for the content.

#### Data and code.

The repository, database schema, run archives and the analysis scripts for this paper (`paper/` in the repository) are at <https://github.com/tazeemc/Redhood-Systems>. Daily closes were obtained from Yahoo Finance’s public chart endpoints on 23 October 2026 (Appendix 13).

# Mathematical derivations

## Mixture entropy

Let $X$ take values in ordinary states $\mathcal O$ with total mass $1-\pi$ and tail states $\mathcal T$ with total mass $\pi$; write $p_i=P(X=i\mid X\in\mathcal O)$ and $q_j=P(X=j\mid X\in\mathcal T)$. Let $B=\mathbb 1[X\in\mathcal T]$. The chain rule gives $H(X)=H(B)+H(X\mid B)=h(\pi)+(1-\pi)H(p)+\pi H(q)$, which is [eq:mixture]. Version 2’s expression $-k\sum p_i\ln p_i+\beta\sum q_j\ln q_j$ is recovered only with $\beta<0$ and after absorbing $h(\pi)$; the sign in Version 2 was an error.

## Equilibrium occupation entropy

If daily returns are Laplace with standard deviation $\sigma$, the scale is $b=\sigma/\sqrt2$ and $F_b(u)=\tfrac12e^{u/b}$ for $u<0$, $1-\tfrac12e^{-u/b}$ for $u\ge0$. For levels with edges $u_0<\dots<u_k$ in units of $\sigma_b=T_{\mathrm{base}}/\sqrt{252}$ and temperature ratio $\tau=T/T_{\mathrm{base}}$, the level masses are $p_\ell(\tau)=F_{\tau/\sqrt2}(u_\ell)-F_{\tau/\sqrt2}(u_{\ell-1})$ and $S_{\mathrm{eq}}(\tau)=-\sum_\ell p_\ell(\tau)\ln p_\ell(\tau)$, which for the levels [eq:levels] gives the values quoted in §2.2. $S_{\mathrm{eq}}$ is increasing in $\tau$ and bounded by $\ln k$; it crosses the shipped band $S_{\mathrm{hi}}=2.034$ at $\tau=1.25$.

## Bias of the plug-in estimators

For a histogram with $k$ occupied cells and $N$ observations the plug-in entropy has expectation $H-\frac{k-1}{2N}+O(N^{-2})$ ; the Miller–Madow correction adds $\frac{k-1}{2N}$. We apply it with $k$ equal to the number of levels (ten) rather than the number of occupied cells, which is slightly conservative when outer levels are empty; the null quantiles are computed with the same convention, so the thresholds are consistent. The plug-in $D_{\mathrm{KL}}(\hat p\|p)$ against a known $p$ is biased upward by the same leading term, which for $k=15$, $N=20$ is $0.35$ nats. The Monte Carlo of §5 confirms a null mean of $0.40$ for the deployed statistic.

## Normalisation of Equation [eq:bp]

With $u=|r-\mu|$, $\int_0^{r_0}e^{-u/\sigma}du=\sigma(1-e^{-r_0/\sigma})$ and $\int_{r_0}^\infty e^{-r_0/\sigma}(r_0/u)^{1+\alpha}du=e^{-r_0/\sigma}r_0/\alpha$; doubling for the two signs gives $Z$. The tempered form of Version 2, $e^{-u/\sigma}(1+u/r_0)^{-\alpha}$, is bounded above by $e^{-u/\sigma}$ for every $\alpha\ge0$, so its tail is at most exponential.

# Reference implementation

The following is the core of `redhood_regime_detector.py` (version 1.4 of the repository), which replaces Listings 1–4 of Version 2. All temperatures are decimals; both thresholds are quantiles of the Laplace null simulated by `calibrate`; the labels of §5.4 were produced by this code.

``` python
T_BASE = 0.15                                      # annualised, decimal
EDGES  = np.array([-np.inf,-3,-2,-1,-.5,0,.5,1,2,3,np.inf])  # fixed levels, units of T_BASE
K = len(EDGES) - 1

def temperature(r, window=20):
    return float(r[-window:].std(ddof=1) * np.sqrt(252))

def occupation_entropy(r, window=60, t_base=T_BASE):
    z = r[-window:] / (t_base / np.sqrt(252)); n = len(z)
    h, _ = np.histogram(z, bins=EDGES); p = h / h.sum(); p = p[p > 0]
    S = min(-(p * np.log(p)).sum() + (K - 1) / (2 * n), np.log(K))   # Miller-Madow
    return S, S / np.log(K)

def laplace_cdf(u, b):
    return np.where(u < 0, 0.5 * np.exp(u / b), 1 - 0.5 * np.exp(-u / b))

def equilibrium_entropy(temp_ratio):                # Boltzmann occupation at T = temp_ratio * T_BASE
    p = np.diff(laplace_cdf(EDGES, temp_ratio / np.sqrt(2))); p = p[p > 0]
    S = -(p * np.log(p)).sum(); return S, S / np.log(K)

def kl_departure(r, window=60, bins=None):
    x = r[-window:]; k = bins or int(np.sqrt(len(x))); b = x.std(ddof=1) / np.sqrt(2)
    h, e = np.histogram(x, bins=k); emp = h / h.sum()
    ref = laplace_cdf(e[1:], b) - laplace_cdf(e[:-1], b); ref /= ref.sum(); m = emp > 0
    return float((emp[m] * np.log(emp[m] / ref[m])).sum())

def calibrate(window=60, t_base=T_BASE, sims=4000, q=0.95, seed=7):
    rng = np.random.default_rng(seed); b = t_base / np.sqrt(252) / np.sqrt(2)
    X = rng.laplace(0, b, size=(sims, window)); k = int(np.sqrt(window))
    S = np.array([occupation_entropy(x, window, t_base)[0] for x in X])
    D = np.array([kl_departure(x, window, k) for x in X])
    return dict(S_hi=np.quantile(S, q), D_hi=np.quantile(D, q), bins=k)

def regime(r, cal, t_base=T_BASE):
    T = temperature(r); S, eta = occupation_entropy(r, 60, t_base)
    S_eq, eta_eq = equilibrium_entropy(T / t_base); D = kl_departure(r, 60, cal['bins'])
    hot, spread, drift = T > t_base, S > cal['S_hi'], D > cal['D_hi']
    label = ('CRISIS' if spread else 'CHOPPY') if hot else ('TRANSITION' if drift else 'TRENDING')
    return dict(T=T, S=S, eta=eta, eta_eq=eta_eq, D=D, label=label, warning=drift)

def position_size(equity, st, heat, heat_max=0.06, f0=0.01, cap=0.02, c=2.5, lam=0.5, t_base=T_BASE):
    if st['label'] == 'CRISIS': return 0.0
    temp_factor    = min((t_base / max(st['T'], 1e-9)) ** 2, c)
    entropy_factor = min(max(np.exp(-(st['eta'] - st['eta_eq']) / lam), 0.25), 1.25)
    heat_factor    = max(0.0, 1 - heat / heat_max)          # heat = sum(loss at stop) / equity
    size = equity * f0 * temp_factor * entropy_factor * heat_factor
    if st['label'] == 'TRANSITION': size = min(size, equity * f0)
    return min(size, equity * cap)
```

# Trading rules (restored and revised)

## Entry rules

1.  Temperature-based entry: enter long when $T<0.8\,T_{\mathrm{base}}$ and momentum is positive; enter short when $T>1.2\,T_{\mathrm{base}}$ and momentum is negative.

2.  Entropy-based filters (revised from Version 2’s “no new entries when $S>2S_{\mathrm{base}}$”, which no estimator could trigger): no new entries in <span class="smallcaps">crisis</span>; sizes at most the base size in <span class="smallcaps">transition</span>; reduce by the entropy factor of [eq:size] when $\eta$ exceeds its equilibrium value.

3.  Redundancy filter (new, a hypothesis for the forward test, not a result): do not add to a long after its second appearance in the narrative stream.

## Exit rules

1.  Stop-loss placement: base stop $=2\times$ATR; adjusted stop $=$ base stop $\times\sqrt{T/T_{\mathrm{base}}}$.

2.  Profit targets: target $=$ entry $+1.5\times$ stop distance; scale out at 50% and 100% of target.

3.  Heat: when portfolio heat reaches $h_{\max}$, no new entries; when it exceeds $h_{\max}$ after a temperature rise, reduce the largest positions first.

# Reproducibility

- **System records.** `redhood.db` (tables `runs`, `feeds`, `narratives`, `narrative_tickers`); the archived regime panels in ; the sizing snapshots in ; all as of 22 October 2026.

- **Prices.** SPY daily OHLC from 23 October 2024 to 22 October 2026 (501 closes, 500 returns) and daily closes for 115 symbols from 23 October 2025, from Yahoo Finance’s `v8/finance/chart` and `v7/finance/spark` endpoints, retrieved 23 October 2026; the partial session of 23 October was discarded. Closes are unadjusted.

- **Ledger construction.** Long-side tickers from `redhood_grader.extract_long_tickers` (repository version 1.4) applied to each hypothesis; BK and TMHC lacked price data. Entry at the first close on or after the run date, or the next session for runs at or after 20:00 UTC; horizons in trading days; excess returns against SPY over identical windows. Themes: energy = XLE, USO, XOP, OXY, CVX, XOM, SLB, HAL, VLO, MPC, PSX, DVN, FANG, UCO, BNO, TTE, EQNR, LNG, GLNG, FLNG, STNG; semiconductors/AI = NVDA, AMD, SMH, SOXL, MU, AVGO, TSM, ASML, KLAC, QCOM, SMCI, DELL, MSFT, GOOGL, ORCL, PLTR, CRM, ADBE. Heat: positions open for 20 sessions from entry, \$2,500 each, 8% stop, \$100,000 equity.

- **Simulation.** Shipped calibration: 4,000 Laplace windows of 60 returns at $T=T_{\mathrm{base}}$, seed 7 (`calibrate` in Appendix 11); Figure 2 and the deployed-statistic nulls use 20,000 windows (seed 7 in the analysis script, seed 3 in the figure script); power: 4,000 windows (seed 21).

- **Density fits.** Maximum likelihood with SciPy; Nelder–Mead from a grid of starting values; the normalising constant of the tempered form by adaptive quadrature and that of Eq. [eq:bp] in closed form. Exact discrete power-law exponents by maximising the zeta-function likelihood.

- **Scripts.** `paper/analysis/` in the repository: `regime_analysis.py`, `entropy_boltzmann.py`, `pnl_analysis.py`, `figures.py`, `make_tables.py`.

<div class="thebibliography">

99 Boltzmann, L. (1872). Weitere Studien über das Wärmegleichgewicht unter Gasmolekülen. *Sitzungsberichte der Kaiserlichen Akademie der Wissenschaften*, 66, 275–370. Chowdhury, T. (2022). Interpreting Black Swans, Boltzmann with a Thermodynamic Bias: a working paper. SSRN 4315813. Chowdhury, T. (2025). Interpreting Black Swans & Boltzmann with a Thermodynamic Bias. SSRN 5111819. Clauset, A., Shalizi, C. R., and Newman, M. E. J. (2009). Power-law distributions in empirical data. *SIAM Review*, 51(4), 661–703. Cont, R. (2001). Empirical properties of asset returns: stylized facts and statistical issues. *Quantitative Finance*, 1(2), 223–236. Cover, T. M. and Thomas, J. A. (2006). *Elements of Information Theory*, 2nd ed. Wiley. Evans, D. J. and Searles, D. J. (2002). The fluctuation theorem. *Advances in Physics*, 51(7), 1529–1585. Fama, E. F. (1970). Efficient capital markets: a review of theory and empirical work. *Journal of Finance*, 25(2), 383–417. Gabaix, X., Gopikrishnan, P., Plerou, V., and Stanley, H. E. (2003). A theory of power-law distributions in financial market fluctuations. *Nature*, 423, 267–270. Jaynes, E. T. (1957). Information theory and statistical mechanics. *Physical Review*, 106(4), 620–630. Kullback, S. and Leibler, R. A. (1951). On information and sufficiency. *Annals of Mathematical Statistics*, 22(1), 79–86. Mandelbrot, B. (1963). The variation of certain speculative prices. *Journal of Business*, 36(4), 394–419. Markowitz, H. (1952). Portfolio selection. *Journal of Finance*, 7(1), 77–91. Miller, G. A. (1955). Note on the bias of information estimates. In *Information Theory in Psychology: Problems and Methods*, 95–100. Free Press. Paninski, L. (2003). Estimation of entropy and mutual information. *Neural Computation*, 15(6), 1191–1253. Searles, D. J. and Evans, D. J. (1999). The fluctuation theorem for stochastic systems. *Physical Review E*, 60, 159–164. Seykota, E. (1991). Trading system heat. *Technical Analysis of Stocks and Commodities*, 9(1), 42–45. Shannon, C. E. (1948). A mathematical theory of communication. *Bell System Technical Journal*, 27(3), 379–423. Stratonovich, R. L. (1992). *Nonlinear Nonequilibrium Thermodynamics I: Linear and Nonlinear Fluctuation-Dissipation Theorems*. Springer. Taleb, N. N. (2001–2018). *Incerto: Fooled by Randomness; The Black Swan; The Bed of Procrustes; Antifragile; Skin in the Game*. Random House and Penguin. Zipf, G. K. (1949). *Human Behavior and the Principle of Least Effort*. Addison-Wesley.



[^1]: Research, Redhood Capital, Canada. `redhoodcapital@protonmail.com`. Independent researcher. Version 3, October 2026. Version 1 (December 2022) and Version 2 (January 2025) are available as SSRN 4315813 and SSRN 5111819.

[^2]: <https://github.com/tazeemc/Redhood-Systems>. The analysis in this paper is reproducible from the repository’s SQLite database (`redhood.db`), its archived run outputs, and public daily closes; see Appendix 13.
