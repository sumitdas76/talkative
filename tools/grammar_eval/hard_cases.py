"""Hand-written grammar-stage inputs aimed at known failure modes.

Each case: (category, input, must_keep, must_not)
  must_keep: lowercase words/phrases that must appear in the output (the
             meaning-bearing bits -- idioms, pronouns, negations, modals,
             names, numbers).
  must_not:  lowercase words/phrases that must NOT appear (the classic
             wrong rewrites).
Inputs mimic what reaches the grammar stage: after filler removal and
the rule-based correction/repeat passes, in both Cloud (punctuated) and
Local small.en (often loosely punctuated) styles.
"""

CASES = [
    # --- already clean: should come back (nearly) unchanged ---
    ("clean", "I need to fix the login bug before Friday.", ["before friday", "i need"], []),
    ("clean", "Can you send me the updated invoice by tomorrow morning?", ["can you", "?", "tomorrow morning"], []),
    ("clean", "The meeting went well, but we still need a decision on the budget.", ["went well", "budget"], []),
    ("clean", "Thanks for the quick turnaround on this. Really appreciate it.", ["quick turnaround", "appreciate"], []),

    # --- idioms / the speaker's own phrasing ---
    ("idiom", "I don't know what's happening man, but I think everything is going to the dogs.", ["going to the dogs"], ["falling apart"]),
    ("idiom", "Honestly the new design is a bit of a mixed bag but let's run with it.", ["mixed bag", "run with it"], []),
    ("idiom", "We're not out of the woods yet so don't celebrate too early.", ["out of the woods"], []),
    ("idiom", "That deadline is way too tight, we are basically burning the candle at both ends.", ["burning the candle at both ends"], []),

    # --- pronouns: who does what ---
    ("pronoun", "I want you to take care of this going ahead.", ["i want you"], []),
    ("pronoun", "If I create videos in a higher resolution will there be a difference in quality?", ["if i create", "?"], ["if you create"]),
    ("pronoun", "before I do that what I want you to do is explain the whole flow to me", ["before i do", "want you"], ["before you do"]),
    ("pronoun", "we should tell them that they need to sign the form before we can proceed", ["we should", "they need", "we can"], []),
    ("pronoun", "my manager said I can take Friday off if I finish the report", ["my manager", "i can", "if i finish"], ["you can"]),

    # --- negation / modality / certainty ---
    ("negation", "I won't be able to make it to the call tomorrow.", ["won't"], ["will be able"]),
    ("negation", "we never agreed to that price and we can't accept it now", ["never", "can't"], []),
    ("modal", "the shipment might arrive on Monday but I'm not sure", ["might", "not sure"], ["will arrive"]),
    ("modal", "maybe we should push the launch by a week", ["maybe"], []),
    ("negation", "it's not that I don't like the idea, I just don't think we have time", ["don't like", "don't think"], []),

    # --- questions ---
    ("question", "will there be any difference in sound quality?", ["?"], ["there will be no"]),
    ("question", "do you think we should hire someone or just outsource it", ["?"], []),
    ("question", "can I check the logs? are they stored locally?", ["?", "locally"], []),

    # --- numbers / names ---
    ("numbers", "The invoice total was 4,250 dollars and it's due on the 15th.", ["4,250", "15th"], []),
    ("numbers", "we need about three hundred units by the end of March", ["march"], []),
    ("numbers", "call me on extension 2047 after 5 pm", ["2047", "5"], []),
    ("names", "Please forward this to Ashwini and Rahul, and cc Priyanka from finance.", ["ashwini", "rahul", "priyanka"], []),
    ("names", "Tell Mr. Bajaj that the Kubernetes cluster is back up.", ["bajaj", "kubernetes"], []),

    # --- needs real cleanup: repeats, false starts, run-ons ---
    ("messy", "the the report needs to needs to go out before the meeting starts", ["report", "before the meeting"], []),
    ("messy", "so what I was trying to say is is that the server the server keeps crashing every night", ["server", "crashing", "every night"], []),
    ("messy", "i was going to i mean i am going to send the proposal on monday", ["send the proposal", "monday"], []),
    ("messy", "can you check if the the build passed because i think it did not pass last time and we need it green before merging", ["build", "green", "merging"], []),
    ("messy", "we tried restarting it didnt work so then we cleared the cache and that also didnt work", ["restarting", "cache"], []),

    # --- garbled: rewording is allowed here ---
    ("garbled", "there's this issue where when the user clicks the button nothing happens sometimes its kind of random", ["button"], []),
    ("garbled", "the thing with the thing is that the export it doesnt the export doesnt include the dates", ["export", "dates"], []),

    # --- long, loosely punctuated (latency + dropped-sentence risk) ---
    ("long", "okay so the thing is that the the deployment failed last night because the config file was pointing at the old database and nobody noticed until the morning when customers started complaining that they could not log in and then we had to roll back which took about an hour because the rollback script itself had a bug in it so going forward i think we need to add a check to the pipeline that validates the config before it goes out and also someone should own the rollback script and test it every month",
     ["deployment failed", "old database", "roll", "about an hour", "every month"], []),
    ("long", "Hi team. Quick update on the migration. We moved 80% of the customer accounts over the weekend. The remaining ones have custom integrations, so we'll need to handle them one by one. I'll share a list by Wednesday. If anyone has context on the older integrations, please reach out to me directly. Thanks.",
     ["80%", "wednesday", "reach out", "thanks"], []),
]
