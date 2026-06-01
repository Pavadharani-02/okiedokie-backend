from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import random
#from transformers import pipeline
import os
from dotenv import load_dotenv
from datetime import datetime
import requests
from flask_socketio import SocketIO, emit, join_room, leave_room


# ---- Flask app setup ----
load_dotenv()
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

socketio = SocketIO(app, cors_allowed_origins="*")


NOTES_DIR = "user_notes"

if not os.path.exists(NOTES_DIR):
    os.makedirs(NOTES_DIR)


def get_user_folder(username):
    """Return (and create if missing) the user folder path."""
    folder = os.path.join(NOTES_DIR, username)
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder


# NOTES_DIR = os.path.join(os.getcwd(), "notes")
# os.makedirs(NOTES_DIR, exist_ok=True)



@socketio.on("join")
def handle_join(data):
    """User or therapist joins a call room"""
    room = data["room"]
    join_room(room)
    emit("message", {"msg": f"{data['username']} joined {room}"}, room=room)


@socketio.on("signal")
def handle_signal(data):
    """Forward signaling data (offer/answer/ICE) to other peer"""
    room = data["room"]
    emit("signal", data, room=room, include_self=False)


@socketio.on("leave")
def handle_leave(data):
    """Handle leaving a room"""
    room = data["room"]
    leave_room(room)
    emit("message", {"msg": f"{data['username']} left {room}"}, room=room)



# ---- SQLite config ----
# ---- PostgreSQL (Neon) config ----

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ---- Database models ----
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(50), nullable=False)

class Mood(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), db.ForeignKey('user.username'), nullable=False)
    mood = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(
        db.String(50),
        db.ForeignKey('user.username'),
        nullable=False
    )

    filename = db.Column(db.String(255))
    content = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

# Create tables
with app.app_context():
    db.create_all()

# ---- Hugging Face pipeline ----
"""emotion_analyzer = pipeline(
    "text-classification",
    model="nateraw/bert-base-uncased-emotion",
    return_all_scores=True
)"""

# ---- Conversation memory ----
user_context = {}  # stores previous messages per user

# ---- Keyword-based emotions ----
emotion_keywords = {
    "happy": ["happy", "glad", "good", "excited", "joy", "fun"],
    "sad": ["sad", "down", "depressed", "unhappy", "cry", "lonely"],
    "angry": ["angry", "mad", "frustrated", "annoyed"],
    "bored": ["bored", "tired", "meh", "dull"],
    "anxious": ["anxious", "nervous", "worried", "stressed"],
    "love": ["love", "affection", "care", "liked"]
}

def detect_emotion_keywords(message):
    message_lower = message.lower()
    for emotion, keywords in emotion_keywords.items():
        if any(word in message_lower for word in keywords):
            return emotion
    return None

def detect_emotion_hf(message):
    try:
        results = emotion_analyzer(message)[0]  
        best = max(results, key=lambda x: x['score'])
        return best['label'].lower()
    except:
        return None

# ---- Routes ----


"""@app.route("/save_note", methods=["POST"])
def save_note():
    data = request.json
    username = data.get("username")
    filename = data.get("filename")
    content = data.get("content")

    if not username or not filename or not content:
        return jsonify({"success": False, "message": "Missing fields"})

    folder = get_user_folder(username)
    filepath = os.path.join(folder, filename)

    # Add timestamp inside file automatically
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content_with_time = f"[Created on {timestamp}]\n\n{content}"

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content_with_time)
        return jsonify({"success": True, "message": "Note saved"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})
"""
@app.route("/save_note", methods=["POST"])
def save_note():
    data = request.json

    username = data.get("username")
    filename = data.get("filename")
    content = data.get("content")

    if not username or not filename or not content:
        return jsonify({
            "success": False,
            "message": "Missing fields"
        })

    existing = Note.query.filter_by(
        username=username,
        filename=filename
    ).first()

    if existing:
        return jsonify({
            "success": False,
            "message": "File already exists"
        })

    note = Note(
        username=username,
        filename=filename,
        content=content
    )

    db.session.add(note)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Note saved"
    })


@app.route("/get_notes/<username>", methods=["GET"])
def get_notes(username):

    notes = Note.query.filter_by(
        username=username
    ).all()

    result = []

    for note in notes:
        result.append({
            "filename": note.filename,
            "content": note.content
        })

    return jsonify({
        "success": True,
        "notes": result
    })


@app.route("/delete_note", methods=["POST"])
def delete_note():
    data = request.json

    username = data.get("username")
    filename = data.get("filename")

    note = Note.query.filter_by(
        username=username,
        filename=filename
    ).first()

    if not note:
        return jsonify({
            "success": False,
            "message": "Note not found"
        })

    db.session.delete(note)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Note deleted"
    })


@app.route("/update_note", methods=["POST"])
def update_note():

    data = request.json

    username = data.get("username")
    filename = data.get("filename")
    content = data.get("content")

    note = Note.query.filter_by(
        username=username,
        filename=filename
    ).first()

    if not note:
        return jsonify({
            "success": False,
            "message": "Note not found"
        })

    note.content = content

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Note updated"
    })


@app.route('/')
def index():
    return "Server is live!"


@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if User.query.filter_by(username=username).first():
        return jsonify({"success": False, "message": "Username already exists"}), 400

    user = User(username=username, password=password)
    db.session.add(user)
    db.session.commit()
    return jsonify({"success": True, "message": "Signup successful!"})

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    user = User.query.filter_by(username=username, password=password).first()
    if user:
        return jsonify({"success": True, "message": "Login successful!"})
    else:
        return jsonify({"success": False, "message": "Invalid username or password"}), 401

@app.route('/submit_mood', methods=['POST'])
def submit_mood():
    data = request.get_json()
    username = data.get("username")
    mood_text = data.get("mood").strip().lower()

    if not User.query.filter_by(username=username).first():
        return jsonify({"success": False, "message": "User not found"}), 404

    mood_entry = Mood(username=username, mood=mood_text)
    db.session.add(mood_entry)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/mood_history/<username>', methods=['GET'])
def get_mood_history(username):
    moods = Mood.query.filter_by(username=username).order_by(Mood.timestamp).all()
    history = [{"datetime": m.timestamp.strftime("%Y-%m-%d %H:%M"), "mood": m.mood} for m in moods]
    return jsonify({"history": history})

# ---- Chatbot ----
@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    print("Chat endpoint hit!")
    message = data.get("message")
    username = data.get("username")

    if username not in user_context:
        user_context[username] = []

    # store message in context
    user_context[username].append(message)

    # --- Detect emotion ---
    emotion = detect_emotion_keywords(message) or "neutral"

    # --- Generate empathetic reply ---
    replies = {
        "happy": [
            "That's wonderful! 😊 What made you feel happy today?",
            "Glad to hear you're in a good mood 😄",
            "Happy vibes are contagious 🌟 Keep it up!"
        ],
        "sad": [
            "I'm really sorry you're feeling sad 💙 Want to share more?",
            "It’s okay to feel low sometimes. I’m here if you want to talk 💛",
            "That must be tough 😔. Do you want to talk it out?"
        ],
        "angry": [
            "I can sense your frustration 😠. Want to vent?",
            "It's normal to feel angry sometimes. Want to tell me what happened?",
            "Anger can be overwhelming 💢. Talking might help."
        ],
        "bored": [
            "Boring days can feel endless 😌. Want me to suggest something fun?",
            "I get it, boredom hits hard sometimes 😅",
            "Maybe trying something new could help break the boredom 🤔"
        ],
        "anxious": [
            "I hear you. Anxiety can be really tough 😟",
            "That sounds stressful 💜. Do you want to share what’s worrying you?",
            "It’s okay to feel anxious 🌿. Let’s take it one step at a time."
        ],
        "love": [
            "Aww, that’s sweet 💖 Love is beautiful!",
            "Love makes life so much brighter 🥰",
            "That’s heartwarming 💕 Want to tell me more?"
        ],
        "neutral": [
            "I see. Can you tell me a bit more about how you feel? 🤔",
            "Got it 👍. Want to share more?",
            "I’m listening 👂. Tell me more about your feelings."
        ]
    }
    reply = random.choice(replies.get(emotion, ["I see. Can you tell me a bit more about how you feel? 🤔"]))

    # store mood in DB
    if User.query.filter_by(username=username).first():
        mood_entry = Mood(username=username, mood=emotion)
        db.session.add(mood_entry)
        db.session.commit()

    return jsonify({"reply": reply, "emotion": emotion})


# ---- Daily Quote ----

@app.route("/daily_quote")
def daily_quote():
    try:
        # Fetch random quote from ZenQuotes API
        response = requests.get("https://zenquotes.io/api/quotes/random", timeout=5)
        if response.status_code == 200:
            data = response.json()
            # ZenQuotes returns a list of quotes
            quote = data[0].get("q", "Stay positive and keep going!")
            author = data[0].get("a", "Unknown")
            return jsonify({"quote": quote, "author": author})
    except Exception as e:
        print("Quote API error:", e)

    # Fallback quotes if API fails
    fallback_quotes = [
        {"text": "Keep pushing forward!", "author": "Unknown"},
        {"text": "Believe in yourself and all that you are.", "author": "Unknown"},
        {"text": "Every day is a second chance.", "author": "Unknown"},
        {"text": "Happiness depends upon ourselves.", "author": "Aristotle"},
        {"text": "Turn your wounds into wisdom.", "author": "Oprah Winfrey"}
    ]
    quote = random.choice(fallback_quotes)
    return jsonify({"quote": quote["text"], "author": quote["author"]})

# ---- Spotify Mood Links ----
spotify_links = {
    "happy": "https://open.spotify.com/playlist/37i9dQZF1DXdPec7aLTmlC",
    "sad": "https://open.spotify.com/playlist/37i9dQZF1DX7qK8ma5wgG1",
    "bored": "https://open.spotify.com/playlist/37i9dQZF1DX0BcQWzuB7ZO",
    "angry": "https://open.spotify.com/playlist/37i9dQZF1DWYxwmBaMqxsl",
    "anxious": "https://open.spotify.com/playlist/37i9dQZF1DWVrtsSlLKzro",
    "love": "https://open.spotify.com/playlist/37i9dQZF1DWXbttAJcbphz",
    "neutral": "https://open.spotify.com/playlist/37i9dQZF1DX4WYpdgoIcn6"
}

@app.route("/spotify/<mood>", methods=["GET"])
def spotify(mood):
    if mood in spotify_links:
        return jsonify({"link": spotify_links[mood]})
    return jsonify({"error": "Mood not found"}), 404


# ---- Main ----
if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=True
    )

