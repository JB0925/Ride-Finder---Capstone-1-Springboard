import os

from decouple import config
from flask import Flask, redirect, render_template, url_for, session, request, jsonify, flash
from flask_bcrypt import Bcrypt
from flask_cors import CORS, cross_origin

from forms import GetEmailForm, RegistrationForm, LoginForm, ResetPasswordForm, RouteSearchForm
from models import OriginInfo, db, connect_db, User, Search, Station, StationDirection, RouteData
import get_routes as gr
from sms import send

app = Flask(__name__)
CORS(app, support_credentials=True)

app.config['SECRET_KEY'] = config('SECRET_KEY')

# Heroku uses the "postgres" prefix for their database urls,
# but this no longer works, hence the workaround below.
try:
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL").replace("://", "ql://", 1)
except AttributeError:
    # this is used locally and used to run tests
    app.config['SQLALCHEMY_DATABASE_URI'] = config('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

connect_db(app)
db.create_all()

# global variables used to send data for client-side requests
MAP_ARRAY = ['map', 'hybrid', 'satellite', 'dark', 'light']


"""
User registration, login, and logout methods, as well as a 404
page and an About page.
"""

@app.route('/', methods=['GET', 'POST'])
def signup():
    """
    Method used to render the home / registration
    page and create a new user in the database.
    """
    form = RegistrationForm()

    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        email = form.email.data
        user = User.register(username, password, email)
        db.session.add(user)
        db.session.commit()
        session['username'] = username
        flash('Your registration was successful!')
        return redirect(url_for('search_stations'))

    if "username" in session:
        return redirect(url_for('search_stations'))
    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Method used to render the login page and login
    an existing user.
    """
    if session.get("email"):
        session.pop("email")

    form = LoginForm()

    if request.method == 'GET':
        if not session.get("username"):
            return render_template('login.html', form=form)
        return redirect(url_for('search_stations'))
    
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        user = User.authenticate(username, password)

        if user:
            session['username'] = username
            flash('Logged in successfully!')
            return redirect(url_for('search_stations'))

    flash('Your account was not found. Please sign up today!')
    return redirect(url_for('signup'))


@app.route('/logout')
def logout():
    """Handles logging out a user."""
    session_keys = "username num_routes num_stations email".split()
    for key in session_keys:
        if session.get(key):
            session.pop(key)

    flash('You were successfully logged out!')
    return redirect(url_for('login'))


@app.route('/about')
def about():
    """
    A page solely used to display the purpose
    of the app and the technologies used to create it.
    """
    return render_template('about.html')


@app.route('/404')
def not_found():
    """
    A page used when a user types in information
    for which there is no match.
    """
    return render_template('404.html')


"""
Searching for transit stations, showing station results and upcoming routes.
"""

@app.route('/search', methods=['GET', 'POST'])
def search_stations():
    """
    Method used to locate public transit stations within a 
    500 meter radius of the address given by the user.
    """
    user = User.query.filter_by(username=session.get('username')).first()
    if not user:
        return redirect(url_for('login'))
        
    form = RouteSearchForm()

    if form.validate_on_submit():
        full_address = form.street_address.data

        try:
            lat, lng = gr.get_lat_and_long(full_address)
        except TypeError:
            return redirect(url_for('not_found'))
        
        origin_info = OriginInfo(city_and_state=full_address, latitude=str(lat), longitude=str(lng), user_id=user.id)
        db.session.add(origin_info)
        db.session.commit()

        # gets data about stations and then packages it into an easier to read format
        all_routes_and_stations = gr._get_routes_and_stations(lat,lng)
        only_stations = gr.get_station_data(all_routes_and_stations)
        
        if only_stations:
            Station.batch_commit(only_stations, user.id)
            station_directions = [gr.get_directions_to_station(full_address, f'{only_stations[i][0]} {full_address}') \
                                    for i in range(len(only_stations))]
            StationDirection.batch_commit(station_directions, user.id)
            return redirect(url_for('show_station_results'))
        return redirect(url_for('not_found'))
    
    # handles any GET requests based on whether the user is logged in or not
    if "username" in session:
        return render_template('search.html', form=form)
    return redirect(url_for('login'))


@app.route('/search/results')
def show_station_results():
    """
    Renders the page to show transit stations located near
    the address the user gave. Passes the global stations
    variable to the template, as well as an array used to
    give each map an id (used in rendering the maps).
    """
    user = User.query.filter_by(username=session.get('username')).first()
    if not user:
        return redirect(url_for('login'))
    
    origin = user.origins[-1]
    station_data = gr._get_routes_and_stations(float(origin.latitude),float(origin.longitude))
    stations = gr.get_station_data(station_data)
    session["num_stations"] = len(stations)
    length = session["num_stations"]
    stations = [s.serialize for s in user.stations[-length:]]
    station_directions = [d.directions.split('+') for d in user.directions[-length:]]
    return render_template('station_results.html', routes=stations, directions=station_directions, maps=MAP_ARRAY)


@app.route('/stations/<idx>/routes')
def show_route_results(idx):
    """
    Shows a list of all routes and their relevant information,
    as well as setting data to be used in a client-side call
    that is used to render the maps.
    """
    idx = int(idx)
    user = User.query.filter_by(username=session.get("username")).first()
    if not user:
        return redirect(url_for('login'))

    if idx < 0 or idx > 4:
        flash('Sorry, there are not that many available routes!')
        return redirect(url_for('search_stations'))

    origin = user.origins[-1]
    route_information = gr.get_route_data(origin.city_and_state)[idx][0]
    session['num_routes'] = len(route_information)
    num_routes = session["num_routes"]
    
    # handling GET requests and edge cases.
    if not route_information:
        return redirect(url_for('search_stations'))
    
    origin_lat_and_lng = {"latitude": origin.latitude, "longitude": origin.longitude}
    route_names = gr.save_route_data_to_db(route_information, origin_lat_and_lng, user, origin)
    available_routes = user.searches[-num_routes:]
    return render_template('route_results.html',routes=available_routes, maps=MAP_ARRAY, names=route_names)


"""
Routes called on the client side to get data from the server side.
Used to render maps with the correct data.
"""
@app.route('/get_stations')
@cross_origin(supports_credentials=True)
def get_stations():
    """
    A route used by the client-side to get data
    about the stations that will allow maps to 
    be rendered.
    """
    user = User.query.filter_by(username=session.get("username")).first()
    length = session.get("num_stations")

    if not user or not length:
        return jsonify({"Error": "Could not complete request. Please log in or sign up."})
    stations = user.stations[-length:]
    results = {}
    i = 0
    for item in stations:
        temp = []
        temp.append(item.name)
        temp.append(item.station_latitude)
        temp.append(item.station_longitude)
        results[i] = temp
        i += 1
    return jsonify(results)


@app.route('/get_routes')
@cross_origin(supports_credentials=True)
def get_routes():
    """
    A route used by the client-side to get data
    about the routes for a selected station. It
    also gives the client-side the data that allows
    the maps to be rendered.
    """
    user = User.query.filter_by(username=session.get("username")).first()
    num_routes = session.get('num_routes')
    if not user or not num_routes:
        return jsonify({"Error": "Could not complete request. Please log in or sign up."})
    routes = [[r.serialize for r in user.routes[-num_routes:]]]
    route_destination_coords = [(float(r["latitude"]), float(r["longitude"])) for item in routes for r in item]
    
    origin = user.origins[-1]
    origin_lat_and_lng = {"latitude": float(origin.latitude), "longitude": float(origin.longitude)}

    routes.append(origin_lat_and_lng)
    routes.append(origin.city_and_state)
    routes.append(route_destination_coords)
    
    return jsonify(routes)


"""
Routes called to check to see if a user has an account.
If they do, a 'reset password' email will be sent with 
a temporary password. The user will then enter the 
temporary password, and then their new password, which
will be hashed and stored in the database as a replacement
for their old password.
"""

@app.route('/reset/email', methods=['GET', 'POST'])
def check_email():
    """
    A page used to ensure that a logged out user 
    has an account on the website.
    """
    form = GetEmailForm()
    dummy_pw = config('TEMP_PW')
    
    if form.validate_on_submit():
        user_email = form.email.data
        session["email"] = form.email.data
        user = User.query.filter_by(email=user_email).first()
        if user:
            msg = f"Thank you for contacting Ride Finder.\
                Your temporary password is {dummy_pw}.\
            - The Ride Finder Team"
            send(msg, user.email)
            return redirect(url_for('reset_password', email=form.email.data))

        flash('Sorry, your email is not associated with an account!')
        return redirect(url_for('signup'))

    return render_template('reset_get_email.html', form=form)


@app.route('/reset', methods=['GET', 'POST'])
def reset_password():
    """
    Route that prompts the user to enter a temporary password
    that was emailed to them. Then, they will also enter a 
    new password, which will then be updated in the database.
    """
    
    dummy_pw = config('TEMP_PW')
    form = ResetPasswordForm()
    
    if form.validate_on_submit():
        temp_pw = form.temp_password.data
        if temp_pw == dummy_pw:
            bcrypt = Bcrypt()
            if len(form.new_password.data) < 8:
                flash("Your password must be eight characters long.")
                return redirect(url_for("reset_password"))
            new_hashed_pw = bcrypt.generate_password_hash(form.new_password.data).decode('utf-8')
            user = User.query.filter_by(email=session.get("email")).first()
            user.password = new_hashed_pw
            db.session.add(user)
            db.session.commit()
            flash('Your password was successfully reset!')
        else:
            flash('Sorry, the temporary password you entered was incorrect. Please request another email to reset it.')
        
        return redirect(url_for('login'))
    
    return render_template('reset.html', form=form)