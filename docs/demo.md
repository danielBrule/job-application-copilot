# Five-minute demo

This walkthrough demonstrates the application with fictional material only. The public source
content is under [`examples/portfolio-demo`](../examples/portfolio-demo/); it must never be mixed
with real career documents or an API key in screenshots, commits or issue attachments.

## Prepare a local demo

1. Follow [local setup](local-operations.md#setup-and-configuration) and copy `.env.example` to
   `.env`.
2. Create or update the local environment: `.\dev.ps1 env`

3. Set `JAC_DATA_DIR` to a disposable local folder, rather than your normal private-data folder.
4. Create local DOCX versions of the fictional Document A and Document B source in
   [`fictional-inputs.md`](../examples/portfolio-demo/fictional-inputs.md). Do not alter the stated
   confidence labels or constraints.
5. Add the fictional job description from the same file in the Jobs screen.
6. Start the app with `./dev.ps1 ui`, configure the fictional reference assets and run the explicit
   assessment action. A live OpenAI call requires your own configured key and may incur charges.

The Markdown source is intentionally committed instead of generated DOCX files so the portfolio
repository stays readable and avoids representing synthetic artifacts as personal career records.

## Reviewer path

1. **Dashboard:** show the local workflow KPIs and navigation.
2. **Jobs:** open the fictional Northstar Systems role; show that assessment is user-triggered.
3. **Assessment:** show fit, evidence anchors, gaps and anti-overclaiming constraints. Explain
   that Document A—not Document B—drives this decision.
4. **Confirm the narrative:** show the recommended CV lane, then explicitly confirm or change it.
   Explain that this decision deterministically controls the authorised Document B material.
5. **Generate the CV:** explicitly approve generation, show the completed background task and open
   the fictional DOCX in Word. Explain that the document remains unapproved until a person reviews
   it; never represent an unreviewed output as final.
6. **Settings:** show versioned reference assets and the active/inactive distinction.
7. **Background Runs:** show durable task state, attempts and guarded retry behaviour.

Generation should only be demonstrated after explicitly confirming the lane and generation action.
Do not present a generated output as approved unless you have manually reviewed it.

## Screenshot checklist

Save public images in `docs/images/` using these exact names:

| File | Screen |
| --- | --- |
| [01-dashboard.png](images/01-dashboard.png) | Dashboard | 
| [02-jobs.png](images/02-jobs.png) | Jobs dashboard | 
| [03-assessment.png](images/03-assessment.png) | Assessment tab | 
| [04-cv-generation.png](images/04-cv-generation.png) | Confirmed lane and generated fictional CV |
| [05-settings.png](images/05-settings.png) | Settings / reference assets | 
| [06-background-runs.png](images/06-background-runs.png) | Background Runs | 
