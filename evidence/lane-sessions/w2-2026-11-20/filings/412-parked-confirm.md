## #412 steps 4-7 - PARKED CONFIRMED, unblocker unchanged: the owner-signed-in browser window

**State:** steps 1-3 (fresh-profile auth modal, empty-code feedback, wrong-code 401) were measured earlier on the GUI lane; steps **4-7** remain unrun, and this lane did not run them in this pass.

**Why it cannot be run by this lane:** steps 4-7 require a real owner-signed-in browser window (create a pairing code in a signed-in window, redeem it from a second profile, exercise `gui-open.url` recovery after stop, and `serve --open` reuse), with screenshots. That is exactly the owner-signed-in window the operator holds; a lane process cannot authenticate as the owner's browser, and a headless substitute would not be the artefact the acceptance clause names.

**Unblocker:** an owner-signed-in browser window granted to this lane (or the owner running the four steps with screenshots). No code change unblocks it; nothing in the repo is missing for it to run.

**Up to date:** yes - #412's acceptance text is unchanged, and no landing since `4ccee99` alters the auth UI it names. Parked and proceeded from, not waited on.
