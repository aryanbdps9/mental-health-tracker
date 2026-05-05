# Mental Health Tracker

A local-first web app for filling out mental health questionnaires daily. Tracks your answers over time so you can bring structured data to your therapist instead of relying on memory.

## Questionnaires

- PHQ-9 (depression, recall: 2 weeks)
- GAD-7 (anxiety, recall: 2 weeks)
- C-SSRS (suicidal ideation, recall: since last visit)
- ASRS v1.1 (ADHD, recall: 6 months)
- MDQ (bipolar screening, recall: lifetime)

## Requirements

- Python 3.10+
- Flask

```
pip install -r requirements.txt
```

## How it works

Start the server:

```
python app.py --password yourpassword
```

The server picks a random available port and prints the URL to the terminal. Open it in a browser and log in with your password.

On the home screen, click "Daily Check-in". You'll see a list of all questionnaires with checkboxes - pick which ones you want today, drag to reorder, and hit Start. The order and selection are saved for next time.

Questions are presented one at a time. Related questions across questionnaires are linked - answering one can pre-fill or dim options on others (e.g., answering the SI question on PHQ-9 cascades into C-SSRS). Options that would contradict an earlier answer are dimmed but still selectable. If you do select one, the app shows the contradiction and offers to resolve it automatically.

Answers autosave every 600ms. Close the browser mid-session and it resumes where you left off next time you open the app.

After completing each questionnaire you see a review screen - tap any answer to go back and edit it. Submit moves to the next questionnaire (or finishes the check-in).

History shows all past entries with search, filter by questionnaire, sort by date, and bulk delete. Times are stored in UTC and displayed in local time as `yyyy/mm/dd HH:mm`.

## Options

```
python app.py --password secret --port 5000 --auto-shutdown 30
python app.py --password secret --data-dir "D:\OneDrive\MentalHealthData"
```

- `--password` (required) - login password
- `--port` - fixed port instead of random
- `--data-dir` - data storage location (remembered for next time)
- `--auto-shutdown N` - exit after N minutes of inactivity

## Data

Entries are self-contained JSON files in `~/.mental-health-tracker/data/entries/`. Point `--data-dir` at a cloud-synced folder and it syncs automatically - you only need to pass `--data-dir` once, it's saved locally for next time.

## Adding questionnaires

Drop a `.json` file in `questionnaires/`. The app picks it up on next launch.
