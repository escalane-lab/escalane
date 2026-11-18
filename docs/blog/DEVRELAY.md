# Publishing this post via DevRelay

[DevRelay](https://devrelay.com/) stages a **private DEV draft** (`create_article`, `published: false`).

Public repo to link: https://github.com/escalane-lab/escalane  
Paste body: [`devto-paste-ready.md`](devto-paste-ready.md)

## Setup

```bash
devrelay login   # MLH account with DEV linked
# Restart Cursor so user-devrelay-gateway loads
```

## Stage draft

Call `create_article` with title/tags from the paste-ready file, `published: false`. Hand the user **`edit_url`**. Upload cover `assets/escalane-dev-cover.jpg` in the DEV UI. Publish only after an explicit yes.
