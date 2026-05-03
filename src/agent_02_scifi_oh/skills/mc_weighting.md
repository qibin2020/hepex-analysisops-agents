# MC Weighting Skill

Use this skill whenever the task includes Monte Carlo samples, simulated
backgrounds, signal templates, or MC weighting fields.

Data events must remain unweighted. MC events should be luminosity-normalized
with the available sample-level and event-level factors. For ATLAS Open Data
style ntuples, the default pattern is:

`weight = lumi_fb_inv * 1000 * xsec * filteff * kfac * mcWeight * scale_factors / sum_of_weights`

Important details:

- The factor `1000` converts fb^-1 times pb into expected event counts.
- `sum_of_weights` is a sample-level normalization denominator from generation,
  not the sum of selected event weights after cuts. Do not recompute it from the
  selected events.
- Use scale factors that exist in the files and are relevant to the objects in
  the task, such as `ScaleFactor_PILEUP`, `ScaleFactor_ELE`,
  `ScaleFactor_MUON`, `ScaleFactor_LepTRIGGER`, `ScaleFactor_ElTRIGGER`,
  `ScaleFactor_MuTRIGGER`, `ScaleFactor_FTAG`, or `ScaleFactor_JVT`.
- For stacked MC histograms, fill bins with MC weights. The MC statistical
  uncertainty per bin is `sqrt(sum(w^2))`.
- If a required branch is missing or inconsistent, record the missing fields,
  the fallback strategy, and how that limits the interpretation. Do not present
  unweighted MC as fully normalized MC.
- Run a data/MC scale sanity check before making a strong physics claim. If the
  MC expectation is orders of magnitude away from the observed data scale,
  report that limitation clearly.
