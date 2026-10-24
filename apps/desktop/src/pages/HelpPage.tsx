import { useState } from "react";
import { PageHeader } from "../components/ui";
import type { PageId, PageProps } from "./types";

interface Topic {
  id: string;
  title: string;
  keywords: string;
  paragraphs?: string[];
  steps?: string[];
  destination?: PageId;
  action?: string;
}

const TOPICS: Topic[] = [
  {
    id: "start", title: "1. Start here: what does this app do?", keywords: "begin beginner overview first steps offline demo API",
    paragraphs: [
      "The Lab tries different settings for an AI model on your computer, measures them against the engine’s starting settings, and saves a recipe only when the improvement is supported by the results.",
      "A model is the AI’s data files. An engine, such as llama.cpp or Strata, is the program that runs those files. You need both already on your computer. The installed app starts its local services for you; normal local setup does not need an API key or a terminal.",
      "If you see OFFLINE DEMO MODE, the screens contain sample data. Turn demo mode off in Settings before testing your own hardware."
    ],
    steps: ["Choose your model and engine folders in Settings.", "Wait for model verification, then open Optimize and choose a compatible model and engine.", "Start with Small setup test. Follow it in Live Runs, then read the result in Compare.", "If a winner qualifies, create a recipe and open Recipes to run it."],
    destination: "settings", action: "Open Settings to begin"
  },
  {
    id: "folders", title: "2. Choose folders and an engine", keywords: "setup add folder import discover executable build missing paths",
    steps: [
      "In Settings, use Edit setup if setup is already saved. Choose Add model folder and select the parent folder containing your model files or their subfolders. Select a folder, rather than an individual model file.",
      "Choose Add inference folder and select the parent folder containing your installed llama.cpp or Strata builds. A folder of source code alone may not contain a runnable engine.",
      "Continue to the detected builds and choose Use this build. Review your selections and choose Save setup. You can add more parent folders later.",
      "Open Models to check what was found. If something is missing, check the selected folders and Discovery details, then use Rescan folders. Finish or cancel active tests and stop a running recipe before changing folders or builds."
    ],
    paragraphs: ["Discovery reads the selected model and engine folders without changing their files. Folder selections are saved automatically. Advanced individual paths are for unusual installations."],
    destination: "settings", action: "Open setup in Settings"
  },
  {
    id: "verification", title: "3. Wait for model verification", keywords: "hash progress waiting pending interrupted restart unreadable permission rescan retry files",
    paragraphs: [
      "Verification reads model files to make a digital fingerprint and confirm exactly which files a test uses. Large models can take several minutes or longer. Watch the file and byte progress; you can browse other screens while it runs.",
      "Services running means the app’s background helpers are available. It does not mean every model is verified or that a test can run yet. The final readiness checks still apply.",
      "Unchanged file fingerprints are reused after restarting. Changed files need verification again. If verification fails, review Discovery details, check that the files still exist and are readable, and use Rescan folders in Settings. Repeatedly clicking a readiness check will not make a large file finish sooner."
    ],
    destination: "models", action: "View discovered models"
  },
  {
    id: "test", title: "4. Run your first small test", keywords: "optimize benchmark conservative context 4K candidate replication plan preflight GPU safety",
    steps: [
      "Open Optimize. Choose the local worker (the helper that runs the test), a detected GPU, an engine and a compatible verified model.",
      "For a first run, keep the default goal. At Search depth, choose Small setup test: one 4K context, one candidate, one finalist, one screening run and two final repetitions. It still measures a baseline for comparison.",
      "Keep the quiet-GPU and full-context checks enabled. Close your own GPU-heavy apps and stop any recipe engine before testing. Do not stop unfamiliar system processes.",
      "Continue through Check readiness. Plan ready to submit means the plan can be sent; the worker still checks your files, available GPU and whether the model fits before running.",
      "Review the settings, tick the confirmation and choose Create experiment once. Open Live Runs to follow the test. Duration depends on the model and machine; this preset is a setup check and does not guarantee a validated recipe."
    ],
    destination: "optimize", action: "Open Optimize"
  },
  {
    id: "recovery", title: "5. Follow progress, fix a blocked test, or cancel", keywords: "live runs failed error stuck queued preflight busy memory VRAM unavailable controller offline retry stop cancel",
    paragraphs: [
      "Queued means the test is waiting for a worker. Preflight means it is checking whether it can run safely. Running means measurements are underway. Cancelling means the worker is still stopping the test; wait for the cancelled state.",
      "For a blocked preflight, read the reason in Live Runs, resolve it, then choose Retry preflight. A busy GPU means another application or the desktop is using it. Close apps you recognize and retry when quiet. Do not disable the safety checks to force a result.",
      "If the model does not fit in GPU memory, try a smaller compatible model or a smaller supported context in a new test. Context is the amount of text the model must hold at once.",
      "To stop your test, use Cancel in Live Runs. In the confirmation dialog, Keep running leaves it alone; Cancel test requests a stop and accepts an optional reason. Wait for confirmation before starting another test. If the request fails, read the error and retry.",
      "If services are unavailable, inspect the local lab message and use Retry discovery when offered. Help remains available while services are down. If a folder picker or repeated action fails, record the exact message, action, time and app version from Settings when reporting it."
    ],
    destination: "live", action: "Open Live Runs"
  },
  {
    id: "results", title: "6. Understand results and find saved work", keywords: "no validated winner validation baseline throughput latency confidence evidence recipe saved compare export",
    paragraphs: [
      "Open Compare and select your completed study. Throughput (tokens per second) is how quickly the model processes or generates text. Time to first token is how long you wait before the reply starts. GPU memory use shows how much room the model needs.",
      "The baseline is the engine’s starting configuration measured under the same conditions. A candidate is an alternative set of settings. A validated winner must meet the study’s improvement and confidence requirements, with all required checks passing. The usual gate is at least 5% improvement with 95% confidence.",
      "No validated winner does not by itself mean the test broke. The baseline may already be best, the improvement may be too small or uncertain, or required evidence may be missing. Read the classification and reasons. A Small setup test has a tiny search budget and may find no winner.",
      "Use Export results to save a report. When a qualified winner exists, use Create recipe, then find it in Recipes. Studies and created recipes are saved by the local services; a completed study without a qualified winner will not automatically become a runnable validated recipe. Demo results never qualify."
    ],
    destination: "compare", action: "Open Compare"
  },
  {
    id: "run", title: "7. Use a saved recipe: chat or connect another app", keywords: "run serving local server endpoint API key chat stop recipe model port",
    steps: [
      "Open Recipes and select a validated recipe for the installed model and engine. Verify installation checks that its saved inputs still match; it does not start the engine.",
      "Choose Run recipe. Wait for file verification and the ready state. If launch fails, read the reason, resolve it and explicitly try again. A button click alone does not mean the engine is ready.",
      "When ready, open Chat with this model and send a short message. For another application on this same computer, copy Local API endpoint into its compatible local-server connection settings. The endpoint needs no API key and is not available to other computers.",
      "Use the endpoint shown for the current session; its port can change on a later launch. Use New chat if the conversation becomes too long for the saved context.",
      "Choose Stop engine when finished and wait for it to stop before benchmarking or changing setup. Chat replies are ordinary model use, not new benchmark evidence. A validated performance recipe is not a guarantee of reply quality."
    ],
    destination: "recipes", action: "Open Recipes"
  },
  {
    id: "updates", title: "8. Understand engine recommendations and updates", keywords: "hardware recommended latest installed driver compatibility release asset download GPU",
    paragraphs: [
      "Recommended · latest installed identifies the newest recognizable build already found in your folders. It still needs compatibility checks.",
      "Recommended for your hardware identifies an available update matched to the GPU and driver detected at app startup. Read the selected build and compatibility explanation. Compatibility needs review means the app cannot confidently recommend that build.",
      "Recommendations do not prove an update is faster. Installing an engine update requires explicit confirmation; selecting a different build is a separate action. You do not need to install every update to run your current compatible setup. The app does not update your graphics driver."
    ],
    destination: "settings", action: "Review engine updates in Settings"
  },
  {
    id: "close", title: "9. Close, minimize and return later", keywords: "quit tray reopen persistence saved restart cancel window shutdown",
    paragraphs: [
      "When you close the window, Cancel keeps it open. Minimize to tray hides the window while the local lab keeps running. Reopen it from the tray menu using Show operator console.",
      "Quit stops the local app services. If asked, Stop and quit confirms that active local work will be stopped. To keep a test or recipe engine running, choose Minimize to tray instead.",
      "Your saved setup, studies and recipes remain after relaunch. Unchanged model verification can be reused. Do not assume an interrupted test completed: check Live Runs. A stopped recipe engine must be started explicitly again."
    ]
  }
];

const TERMS = [
  ["GPU / VRAM", "The graphics processor and its own memory. Model size and context affect how much memory is needed."],
  ["Context / token", "Context is the text a model can hold at once. Tokens are small pieces of text; 4K means about 4,096 tokens, not 4,096 words."],
  ["Worker / controller / optimizer", "Background helpers that run tests, save and coordinate work, and choose settings to try. The installed app manages them."],
  ["Preflight / verification", "Preflight checks readiness to run. Verification fingerprints files so results refer to the exact model and engine tested."],
  ["Baseline / candidate / recipe", "Starting settings, alternative settings being tested, and a saved configuration supported by qualifying measurements."],
  ["Screening / finalist / replication", "An initial check, a configuration selected for fuller testing, and a repeated measurement to check consistency."]
];

export function HelpPage({ navigate }: Pick<PageProps, "navigate">) {
  const [search, setSearch] = useState("");
  const query = search.trim().toLocaleLowerCase();
  const topics = TOPICS.filter(topic => [topic.title, topic.keywords, ...(topic.paragraphs ?? []), ...(topic.steps ?? [])].join(" ").toLocaleLowerCase().includes(query));
  const terms = TERMS.filter(term => term.join(" ").toLocaleLowerCase().includes(query));

  return <div className="help-guide">
    <PageHeader eyebrow="No technical background needed" title="Help & guide"
      description="From choosing your folders to your first test and a running model. This guide works offline, even when the local lab needs attention." />
    <label className="field help-search"><span>Search help</span>
      <input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Try: folders, GPU busy, no validated winner, chat" />
    </label>
    {query ? <p role="status">{topics.length} guide {topics.length === 1 ? "topic" : "topics"} and {terms.length} glossary {terms.length === 1 ? "entry" : "entries"} found.
      {" "}<button className="link-button" onClick={() => setSearch("")}>Clear search</button></p> : <p className="help-intro">New here? Follow the numbered topics in order. Already stuck? Search for the message or open the matching topic below.</p>}
    <section aria-label="User guide topics" className="help-topics">
      {topics.map(topic => <details key={topic.id} className="help-topic" open={query ? true : undefined}>
        <summary>{topic.title}</summary>
        <div className="help-topic-body">
          {topic.paragraphs?.map(text => <p key={text}>{text}</p>)}
          {topic.steps ? <ol>{topic.steps.map(text => <li key={text}>{text}</li>)}</ol> : null}
          {topic.destination ? <button className="button button-secondary" onClick={() => navigate(topic.destination!)}>{topic.action}</button> : null}
        </div>
      </details>)}
    </section>
    {terms.length ? <section className="help-glossary" aria-labelledby="help-terms"><h2 id="help-terms">Plain-language glossary</h2>
      <dl>{terms.map(([term, definition]) => <div key={term}><dt>{term}</dt><dd>{definition}</dd></div>)}</dl>
    </section> : null}
    {!topics.length && !terms.length ? <p>No matching help yet. Try “setup”, “verification”, “GPU”, “results” or “recipe”, or clear the search to see the full guide.</p> : null}
  </div>;
}
