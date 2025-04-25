from flask import Flask, request, session, abort, redirect, url_for, jsonify
from pymongo import MongoClient
from dotenv import load_dotenv
from flask_cors import CORS
import certifi
import json, copy, bcrypt, random, os

app = Flask(__name__)
CORS(app, origins=["http://localhost:5173", "http://127.0.0.1:5173", "https://web.postman.co"])
app.secret_key = b'osn82^2h8228'

load_dotenv()
MONGODB_URI = os.environ['MONGODB_URI']
client = MongoClient(MONGODB_URI, tlsCAFile=certifi.where())

db = client['users']
people = db['people']

recommendationDB = client['recommendations']
dashboardCollection = recommendationDB['dashboard_data']

trackingDB = client['tracking']
caloriesCollection = trackingDB['calories']

@app.route("/")
def root():
    return redirect(url_for('login'))

@app.route("/test", methods=['GET'])
def test():
    return "it worked"

@app.route("/login", methods=['POST'])
def login_request():
    logged_in = verify_user()
    ret_str =  jsonify({"message": "Success!"}) if logged_in else jsonify({"message": "Failed!"})
    return ret_str

@app.route("/onboard", methods=['POST'] )
def onboarding():
    return create_user()   

@app.route("/dashboard", methods=['POST'])
def get_dashboard():
    user_data = request.json

    user = people.find_one({"username": user_data['username']})
    if user:
        user["_id"] = str(user["_id"])  # Optional if you're returning user

    dashboard = dashboardCollection.find_one({"username": user_data['username']})
    if dashboard:
        dashboard["_id"] = str(dashboard["_id"])  # 🔧 This line fixes the error

    
    calorieData = caloriesCollection.find({"username": user_data['username']})
    calorieStuff = list(calorieData)
    calorie_history = []
    for item in calorieStuff:
        if "_id" in item:
            item["_id"] = str(item["_id"])
        calorie_history.append(item)

    out = {**dashboard['data'], "calorie_history": calorie_history}
    return jsonify({"data": out})

@app.route("/track", methods=['POST'])
def track_calories():
    calorie_data = request.json
    response = caloriesCollection.insert_one(calorie_data)
    return jsonify({"message": "success"}), 200

@app.route('/logout')
def logout():
    # remove the username from the session if it's there
    session.pop('username', None)
    return 'you have been logged out'

# ---------------------------------------------------------------------- #
def create_user():
    if(request.content_type != 'application/json'):
        abort(415) # if not a json, throw error
    else:
        user_data = request.json
        if people.find_one({"username": user_data["username"]}):
            return jsonify({"error": "User already exists"}), 409
        info = copy.copy(user_data)
        info.pop("username")
        info.pop("password")
        processedData = process_data(info)
        db_data = {
            **user_data,
            "password": bcrypt.hashpw(user_data["password"].encode("utf-8"), bcrypt.gensalt()),
        }
        people.insert_one(db_data)
        dashboardCollection.insert_one({"username": user_data["username"], "data": processedData})
        session["username"] = user_data["username"]
        return json.dumps(info)
    
def verify_user():
    if(request.content_type != "application/json"):
        abort(415) # if not a json, throw error
    else:
        login_data = request.json
        
        if(user := people.find_one({'username': login_data["email"]})):
            if bcrypt.checkpw(login_data["password"].encode("utf-8"), user["password"]):
                session["username"] = login_data["email"]
                return True
            else:
                return False
        else:
            return False
        
def build_diet_message(baseline: dict):
    if(baseline["diet_archetype"] >= 4):
        return diet_dict[2]
    elif(baseline["diet_archetype"] > 2 ):
        return diet_dict[1]
    else:
        return diet_dict[0]
    
def build_lifestyle_message(activity: dict):
    multiplier = activity_level[activity["activity_level"]]
    if(multiplier < 1.4):
        return activity_dict[0]
    elif(multiplier < 1.8 ):
        return activity_dict[1]
    else:
        return activity_dict[2]

def process_data(user_data: dict):
    ret_data = {
        "training": dict()
    }
    # DIET SECTION ------------------------------------------------------------
    stats = user_data["statistics"]
    # calculating TDEE
    BMR = 66 + (6.23 * stats["weight"]) + (12.7 * stats["height"]) - (6.8 * stats["age"])
    TDEE = BMR * activity_level[user_data["daily_activities"]["activity_level"]]
    # calculating a calories surplus/deficit if required
    goals = user_data["goals"]
    if(goals["hasDietaryGoals"]):
        rate_of_change_wk = goals["w_quantity"]/goals["w_timeline"]
        cal_net_diff = (rate_of_change_wk * 7700)/7
        if(goals["w_direction"] == "lose") :
            target_cals = TDEE - cal_net_diff
        else:
            target_cals = TDEE + cal_net_diff
        ret_data["diet"] = {
            "TDEE" : round(TDEE/100) * 100,
            "calories_target" : round(target_cals/100) * 100,
            "quality" : build_diet_message(user_data["diet_baseline"])
        }
    # LIFESTYLE SECTION ------------------------------------------------------- 
    ret_data["activity"] = {
        "steps_target": 10000,
        "sports_activity_hrs_target": 8,
        "activity_desc" : build_lifestyle_message(user_data["daily_activities"])
    }

    # POPULATING TRAINING SECTION -----------------------------------------------
    if("muscle gain" in user_data["goals"]["objectives"]):
        ret_data["training"]["muscle"] = {
            "days/wk": 4,
            "intensity": 8,
            "routine": routines_dict[random.randint(0, 3)]
        }
    if("running" in user_data["goals"]["objectives"]):
        ret_data["training"]["cardio"] = {
            "days/wk" : 3,
            "intensity" : 4,
            "ideas" : cardio_dict[random.randint(0,3)]
        }
    
    # CALCULATE EMPHASIS ---------------------------------------------------
    diet_weight = abs(ret_data["diet"]["TDEE"] - ret_data["diet"]["calories_target"])/500 if goals["hasDietaryGoals"] else 0
    activity_weight = abs(activity_level[user_data["daily_activities"]["activity_level"]] - 2.5) * 3
    training_weight = len(ret_data["training"])
    total_weight = diet_weight + activity_weight + training_weight
    ret_data["emphasis"] = {
        "diet" : diet_weight/total_weight,
        "activity" : activity_weight/total_weight,
        "training" : training_weight/total_weight
    }
    
    return ret_data

cardio_dict = {
    0: "Go for more walks, take a bike ride on the weekends, and try to take up more active opporotunities. If able to, try walking to your friends' house instead of "
    "driving, do some yardwork, and maybe pick up an active hobby.", 
    1: "Try to walk often, maybe pick up jogging or biking as a competitive hobby. Look to push yourself when doing cardiovascular activity to the point where you start to"
    "lose your breath a little bit. Look into endurance sports that may be up your alley.",
    2: "You should try training at a particular sport weekly, and track improvements in your progress over time. Maybe join a club surrounding that sport,"
    "and try to compete with your peers (within reason of course)",
    3: "You should train for your sport of choice weekly, compete with your peers, and optimize your training and diet for results. You can ask your more advanced "
    "peers what techniques they have developed, and adapt them into your own routine."
}

routines_dict = {
    0 : [
        "full body",
        "A full-body split weightlifting routine involves training all major muscle groups in a single workout, typically performed 2-4 times a week. Each session includes compound"
        " exercises like squats, deadlifts, bench presses, and rows, which target multiple muscles at once. This approach is efficient for beginners or those with limited time, as"
        " it allows for balanced muscle development while promoting overall strength and fitness. Since you're working every muscle in each workout, it’s important to ensure adequate"
        " recovery between sessions to avoid overtraining."
    ],
    1 : [
        "upper/lower split",
        "An upper-lower split weightlifting routine involves dividing workouts into two main categories: upper body and lower body. Typically, you’ll alternate between these"
        " two types of workouts, training the upper body (including exercises for the chest, back, shoulders, and arms) on one day and focusing on the lower body (such as squats,"
        " deadlifts, and lunges) on another. This split allows for balanced muscle development and recovery, giving each muscle group enough time to rest between sessions. It’s an "
        "efficient approach for those looking to train multiple times per week while minimizing the risk of overtraining any particular muscle group."
    ],
    2 : [
        "push/pull/legs",
        "A push-pull-legs routine divides workouts into three categories: push, pull, and legs. On push days, you focus on exercises that involve pushing movements, like bench presses,"
        " overhead presses, and tricep extensions, targeting the chest, shoulders, and triceps. Pull days include pulling exercises, such as rows, deadlifts, and bicep curls, working the"
        " back and biceps. Leg days are dedicated to lower body exercises, like squats, lunges, and leg presses, targeting the quads, hamstrings, and glutes. This routine is popular"
        " for its balance, allowing for optimal recovery between muscle groups while training each one multiple times per week."
    ],
    3: [
        "bro split",
        "A bro split is a traditional weightlifting routine where each muscle group is trained on a separate day of the week. Typically, the week is structured with each day focusing on"
        " a specific muscle group, such as chest day, back day, leg day, shoulder day, and arm day (sometimes split into biceps and triceps). This approach allows for intense focus on"
        " one muscle group per session, providing it with maximum volume and effort. While effective for building muscle, the bro split generally limits training frequency for each"
        " muscle group to once per week, which can sometimes hinder recovery and growth for advanced lifters."
    ]
}

activity_dict = {
    0: "You should greatly increase your daily activity. Getting more daily activity is a simple yet powerful way to improve your overall health and well-being. Regular physical activity"
    " helps boost your energy levels, improve mood, and reduce stress. It also supports better cardiovascular health, strengthens muscles, and enhances flexibility. In addition, staying"
    " active can help with weight management and lower the risk of chronic conditions like diabetes and heart disease. To incorporate more movement into your day, try taking the stairs"
    " instead of the elevator, going for a brisk walk during breaks, or engaging in an activity you enjoy, like dancing or biking. Setting small, achievable goals, like aiming for 30"
    " minutes of moderate activity most days of the week, can also keep you motivated and on track.", 
    1: "You're already doing a great job incorporating daily activity into your routine, but there's always room to take things to the next level for even greater health benefits. Regular"
    " movement is key for boosting energy, enhancing mood, and reducing stress, and while you’re staying active, adding just a bit more can help improve your cardiovascular health,"
    " increase strength, and further support weight management. Consider small adjustments like walking a little longer during breaks, opting for a more intense workout a few times a week,"
    " or incorporating activities like yoga or stretching to improve flexibility. By aiming for an extra 10-15 minutes of activity a day, you’ll not only boost your fitness but also feel"
    " even more energized and focused throughout the day.",
    2: "You're already getting more than enough daily activity, which is fantastic for your health! Consistent movement is key to maintaining energy levels, reducing stress, and improving"
    " your overall well-being. With the activity you're already doing, you're supporting your cardiovascular health, building strength, and keeping your body in great shape. It’s important"
    " to listen to your body, though, and if you're already meeting or exceeding recommended activity levels, it might be beneficial to focus on recovery, rest, or variety in your routine."
    " Activities like stretching, mindfulness, or low-intensity movement can be a great way to maintain your fitness without overdoing it. Keep up the great work, and don’t forget to"
    " prioritize rest when needed to avoid burnout."
}

diet_dict = {
    0 : "Improving your diet can have a profound impact on your overall health and well-being. Right now, some of your current eating habits may be contributing to increased risks for"
    " conditions like heart disease, diabetes, and obesity. A diet high in processed foods, sugar, and unhealthy fats can leave you feeling sluggish, affect your mood, and even interfere"
    " with your sleep. Making small changes to your eating habits can lead to big improvements in how you feel and your long-term health. Start by incorporating more whole foods into"
    " your meals, like fruits, vegetables, lean proteins, and whole grains. Reducing your intake of sugary drinks and processed snacks can also help you feel more energized and improve"
    " digestion. Try planning meals ahead of time to avoid unhealthy last-minute choices, and remember that balance is key—it's okay to indulge every once in a while, as long as most of"
    " your meals are nutrient-rich. Taking these steps can help you feel your best and prevent future health issues.", 
    1: "You’re already doing a great job with your diet, but there are a few small improvements you can make to take it to the next level and boost your overall health. While you're"
    " including some nutritious foods, there may still be room for better balance, especially if you’re consuming too many processed foods, added sugars, or unhealthy fats. These can"
    " leave you feeling fatigued or negatively impact your long-term health. A few simple changes, like adding more colorful vegetables to your meals, choosing whole grains over refined"
    " carbs, or reducing your intake of sugary snacks and drinks, can help you feel more energized and improve your digestion. Experimenting with healthy fats from sources like avocado,"
    " nuts, and olive oil, and incorporating more plant-based meals, can also bring a boost to your nutrient intake. By fine-tuning your current habits, you'll enhance your health and well-being even further!",
    2: "You’re absolutely crushing it with your diet, and it’s clear that you’re making all the right choices for your health. Your commitment to eating nutrient-dense foods is paying off in the way you feel"
     " and look, and it’s a great foundation for long-term wellness. If anything, just keep mixing it up to keep things interesting—experiment with different fruits, veggies, and whole grains to maximize the"
      " variety of nutrients you’re getting. You’re already doing an amazing job, so just continue listening to your body and maintaining that healthy balance. Keep it up!"
}
activity_level = {
    "sedentary" : 1.2,
    "active" : 1.55,
    "very active" : 1.9
}


if __name__ == "__main__":
    app.run(debug=True)
