from flask import Flask, flash, render_template, request, redirect, url_for, abort, jsonify, session
from pymongo import MongoClient
from bson.objectid import ObjectId
import base64
from PIL import Image
import io
import datetime


app = Flask(__name__)
app.secret_key = 'secret@key'

client = MongoClient('localhost', 27017)
db = client['41']
images_collection = db['images']
quizzes_collection = db['quizzes']
results_collection = db['results']

current_score = 0

@app.route('/images')
def images():
    images = list(images_collection.find())
    quizzes = list(quizzes_collection.find())
    return render_template('images.html', images=images, quizzes=quizzes)


@app.route('/')
def index():
    quizzes = list(quizzes_collection.find())
    images = list(images_collection.find())
    image_counts = {str(quiz['_id']): images_collection.count_documents({'quiz_id': str(quiz['_id'])}) for quiz in quizzes}
    return render_template('index.html', quizzes=quizzes, images=images, image_counts=image_counts)


@app.route('/create', methods=('GET', 'POST'))
def create():
    if request.method == 'POST':
        name = request.form['name']
        category = request.form['category']
        quizzes_collection.insert_one({'name': name, 'category': category})
        return redirect(url_for('index'))
    else:
        return redirect(url_for('index'))

@app.route('/edit/<quiz_id>', methods=('GET', 'POST'))
def edit(quiz_id):
    # Find the current quiz based on the quiz_id
    current_quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})
    
    if request.method == 'POST':
        # Update the quiz name and category
        name = request.form['name']
        category = request.form['category']
        quizzes_collection.update_one({'_id': ObjectId(quiz_id)}, {'$set': {'name': name, 'category': category}})

        # Retrieve the updated images for the current quiz
        images = list(images_collection.find({'quiz_id': quiz_id}))

        # Update the quiz_id for any images that have a different quiz_id
        for image in images:
            if image['quiz_id'] != quiz_id:
                images_collection.update_one({'_id': image['_id']}, {'$set': {'quiz_id': quiz_id}})

        return redirect(url_for('edit', quiz_id=quiz_id))
    else:
        # Retrieve the images for the current quiz
        images = list(images_collection.find({'quiz_id': quiz_id}))

        # Get the list of all quizzes
        quizzes = list(quizzes_collection.find({}, {'name': 1, '_id': 1}))

        return render_template('edit.html', quiz=current_quiz, images=images, quizzes=quizzes, current_quiz=current_quiz)





@app.route('/start/<quiz_id>', methods=['GET'])
def start(quiz_id):
    # Reset the session data for the new quiz
    session['images_shown'] = 0
    session['current_page'] = 1
    session['current_score'] = 0

    # Retrieve the quiz data from the database
    quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})

    # Retrieve all the images for this quiz that have a valid score
    all_images = list(images_collection.find({'quiz_id': quiz_id, 'score': {'$exists': True, '$ne': None}}, {'data': 1, '_id': 1, 'score': 1, 'filename': 1}).sort('_id', -1))

    # Get the first 3 image IDs
    first_3_image_ids = [str(img['_id']) for img in all_images[:3]]

    # Get the total number of images for this quiz
    image_count = len(all_images)

    # Store the total image count in the session
    session['total_images'] = image_count

    # Calculate the number of pages needed
    pages_needed = (image_count + 2) // 3  # Round up to include the last partial page

    # Get the image counts for all quizzes
    quizzes = list(quizzes_collection.find())
    image_counts = {str(quiz['_id']): images_collection.count_documents({'quiz_id': str(quiz['_id'])}) for quiz in quizzes}

    # Initialize the current_score to 0
    current_score = 0
    session['current_score'] = current_score

    # Store the current_quiz_id in the session
    session['current_quiz_id'] = quiz_id

    # Create a new record in the results collection
    result_id = results_collection.insert_one({
        'quiz_id': quiz_id,
        'user_id': session.get('user_id', 'unknown'),
        'user_known_as': session.get('user_known_as', 'unknown'),
        'start_time': datetime.datetime.now(),
        'final_score': 0,
        'ip_address': request.remote_addr,
        'browser_version': request.user_agent.browser,
        'quizzes_started': 1,
        'quizzes_completed': 0
    }).inserted_id

    # Store the result_id in the session
    session['result_id'] = str(result_id)

    return render_template('start.html', current_quiz=quiz, quiz=quiz, first_3_image_ids=first_3_image_ids, images_collection=images_collection, ObjectId=ObjectId, current_score=current_score, image_count=image_count, image_counts=image_counts, pages_needed=pages_needed)


@app.route('/pages/<quiz_id>/', methods=['GET'])
@app.route('/pages/<quiz_id>/<image_id>', methods=['GET'])
def pages(quiz_id, image_id=None):
    # Get the current quiz ID from the session
    current_quiz_id = session.get('current_quiz_id')

    # If the current_quiz_id is not found in the session, redirect to the start page
    if current_quiz_id is None or current_quiz_id != quiz_id:
        # Reset the session data for the new quiz
        session['images_shown'] = 0
        session['current_page'] = 1
        session['current_score'] = 0
        return redirect(url_for('start', quiz_id=quiz_id))

    # Retrieve the quiz data from the database
    quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})

    # Retrieve all the images for this quiz that have a valid score, sorted in descending order
    all_images = list(images_collection.find({'quiz_id': quiz_id, 'score': {'$exists': True, '$ne': None}}, {'data': 1, '_id': 1, 'score': 1, 'filename': 1}).sort('_id', -1))

    # Calculate the total number of images with valid scores
    image_count = session['total_images']

    # Get the current page number from the session, or set it to 1 if not set
    current_page = session.get('current_page', 1)

    if image_id:
        start_index = next((i for i, d in enumerate(all_images) if str(d['_id']) == image_id), None)
        if start_index is not None:
            next_image_ids = [str(img['_id']) for img in all_images[start_index + 1:start_index + 4]]
        else:
            next_image_ids = []

        # Update the current score based on the score of the selected image
        selected_image = next((img for img in all_images if str(img['_id']) == image_id), None)
        if selected_image and 'score' in selected_image and isinstance(selected_image['score'], (int, float)):
            current_score = session.get('current_score', 0) + int(selected_image['score'])
            session['current_score'] = current_score
        else:
            current_score = session.get('current_score', 0)

        # Increment the page number
        session['current_page'] = current_page + 1
    else:
        # Get the first 3 image IDs with valid scores for the current page
        start_index = (current_page - 1) * 3
        next_image_ids = [str(img['_id']) for img in all_images[start_index:start_index + 3]]

        # Initialize the current_score to 0
        current_score = session.get('current_score', 0)

        # Increment the number of images shown and the current page
        session['images_shown'] = session.get('images_shown', 0) + 3
        session['current_page'] = current_page + 1

    # Calculate the remaining images
    remaining_images = image_count - session.get('images_shown', 0)

    # Get the image counts for all quizzes
    quizzes = list(quizzes_collection.find())
    image_counts = {str(quiz['_id']): images_collection.count_documents({'quiz_id': str(quiz['_id'])}) for quiz in quizzes}

    # Calculate the number of pages needed
    pages_needed = (image_count + 2) // 3  # Round up to include the last partial page

    # Check if the current page number is greater than the total number of pages needed
    if session.get('current_page', 1) > pages_needed:
        return redirect(url_for('quiz_result', quiz_id=quiz_id))
    else:
        return render_template('pages.html', quiz=quiz, images_collection=images_collection, ObjectId=ObjectId, next_image_ids=next_image_ids, current_score=current_score, remaining_images=remaining_images, image_count=image_count, image_counts=image_counts, current_page=session.get('current_page', 1), pages_needed=pages_needed)

@app.route('/quiz_result/<quiz_id>/', methods=['GET'])
@app.route('/quiz_result/<quiz_id>/', methods=['GET', 'POST'])
def quiz_result(quiz_id):
    current_score = session.get('current_score', 0)
    current_quiz_id = session.get('current_quiz_id')
    current_quiz = quizzes_collection.find_one({'_id': ObjectId(current_quiz_id)})

    # Retrieve the result_id from the session
    result_id = session.get('result_id')

    if result_id:
        # Update the results collection with the final score and mark the quiz as completed
        results_collection.update_one(
            {'_id': ObjectId(result_id)},
            {'$set': {
                'final_score': current_score,
                'completed': True,
                'end_time': datetime.datetime.now()
            }}
        )

    if request.method == 'POST':
        # Get the result image file
        result_image = request.files['result_image']

        # Get the additional parameters
        score_from = int(request.form['score_from'])
        score_to = int(request.form['score_to'])
        result_text = request.form['result_text']

        # Convert the result image to base64 string
        result_image_data = base64.b64encode(result_image.read()).decode('utf-8')

        # Save the result image data and additional parameters to MongoDB
        result_id = results_collection.insert_one({
            'user_id': session.get('user_id', 'unknown'),
            'user_known_as': session.get('user_known_as', 'unknown'),
            'quiz_id': session.get('current_quiz_id', 'unknown'),
            'final_score': current_score,
            'ip_address': request.remote_addr,
            'browser_version': request.user_agent.browser,
            'start_time': datetime.datetime.now(),
            'quizzes_completed': 1
        }).inserted_id

        # Redirect to the same page to display the result image
        return redirect(url_for('quiz_result'))

    # Retrieve the quiz data from the database
    # Retrieve the images for the current quiz that have a score range (not a specific score)
    result_images = list(images_collection.find({'quiz_id': quiz_id, 'score': {'$exists': False}}))

    # Find the result image based on the current score
    result_doc = results_collection.find_one({'quiz_id': current_quiz_id, 'score_from': {'$lte': current_score}, 'score_to': {'$gte': current_score}}, {'data': 1, 'result_text': 1, '_id': 0})

    return render_template('result.html', quiz=current_quiz, result_doc=result_doc, result_images=result_images, current_score=current_score, quiz_id=quiz_id)


@app.route('/upload_image', methods=['POST'])
def upload_image():
    if request.method == 'POST':
        if 'image' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        image = request.files['image']
        if image.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)

        quiz_id = request.form['quiz_id']
        score = request.form['score']
        image_description = request.form.get('image_description', '')
        assignment = request.form.get('assignment', '')

        # Read the image file and convert it to base64
        image_data = image.read()
        base64_data = base64.b64encode(image_data).decode('utf-8')

        # Save the image data and additional parameters to MongoDB
        image_document = {
            'filename': image.filename,
            'data': base64_data,
            'quiz_id': quiz_id,
            'score': int(score),
            'description': image_description,
            'assignment': assignment
        }
        images_collection.insert_one(image_document)

        # Create the thumbnail
        create_thumbnail(image_document['_id'])

        flash('Image uploaded successfully', 'success')

        # Retrieve the updated quiz and images
        quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})
        images = list(images_collection.find({'quiz_id': quiz_id}))
        quizzes = list(quizzes_collection.find())


        current_quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})
    return render_template('edit.html', quiz=quiz, images=images, quizzes=quizzes, current_quiz=current_quiz)

def create_thumbnail(image_id):
    # Retrieve the original image from the database
    image = images_collection.find_one({'_id': ObjectId(image_id)})
    if not image:
        return 'Image not found', 404

    # Decode the base64 image data
    image_data = base64.b64decode(image['data'])

    # Create a thumbnail
    thumbnail = Image.open(io.BytesIO(image_data))
    thumbnail.thumbnail((128, 128), resample=Image.LANCZOS)

    # Convert the thumbnail to base64
    thumbnail_io = io.BytesIO()
    thumbnail.save(thumbnail_io, format='PNG')
    thumbnail_data = base64.b64encode(thumbnail_io.getvalue()).decode('utf-8')

    # Update the image document in the database with the thumbnail data
    result = images_collection.update_one(
        {'_id': ObjectId(image_id)},
        {'$set': {'thumbnail': thumbnail_data}}
    )

    if result.modified_count == 1:
        return 'Thumbnail created successfully', 200
    else:
        return 'Failed to create thumbnail', 500

@app.route('/upload_end_image', methods=['POST'])
def upload_end_image():
    if request.method == 'POST':
        if 'image' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        image = request.files['image']
        if image.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)

        # Retrieve the necessary fields from the "Upload End Image" form
        quiz_id = request.form['quiz_id']
        score_from = request.form.get('score_from')
        score_to = request.form.get('score_to')
        result_text = request.form.get('result_text', '')
        assignment = request.form.get('assignment', '')
        link1 = request.form.get('link1', '')
        link2 = request.form.get('link2', '')
        link3 = request.form.get('link3', '')

        # Read the image file and convert it to base64
        image_data = image.read()
        base64_data = base64.b64encode(image_data).decode('utf-8')

        # Save the image data and additional parameters to MongoDB
        image_document = {
            'filename': image.filename,
            'data': base64_data,
            'quiz_id': quiz_id,
            'score_from': int(score_from),
            'score_to': int(score_to),
            'result_text': result_text,
            'link1': link1,
            'link2': link2,
            'link3': link3,
            'assignment': assignment
        }
        images_collection.insert_one(image_document)

        # Create the thumbnail
        create_thumbnail(image_document['_id'])

        flash('Image uploaded successfully', 'success')

        # Retrieve the updated quiz and images
        quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})
        images = list(images_collection.find({'quiz_id': quiz_id}))
        quizzes = list(quizzes_collection.find())

        current_quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})
        return render_template('edit.html', quiz=quiz, images=images, quizzes=quizzes, current_quiz=current_quiz)

@app.route('/upload_images', methods=['GET'])
def show_upload_form():
    quizzes = list(quizzes_collection.find())
    selected_quiz_id = request.args.get('quiz_id')
    if selected_quiz_id:
        current_quiz = quizzes_collection.find_one({'_id': ObjectId(selected_quiz_id)})
    else:
        current_quiz = None
    return render_template('upload_images.html', quizzes=quizzes, current_quiz=current_quiz)

@app.route('/upload_images', methods=['POST'])
def upload_images():
    if request.method == 'POST':
        quiz_id = request.form.get('quiz_id')
        if not quiz_id:
            flash('No quiz selected', 'error')
            return redirect(url_for('show_upload_form'))

        score = request.form['score']
        image_description = request.form['image_description']
        assignment = request.form['assignment']

        for image in request.files.getlist('images'):
            if image.filename == '':
                flash('No selected file', 'error')
                return redirect(url_for('show_upload_form'))

            image_data = image.read()
            base64_data = base64.b64encode(image_data).decode('utf-8')

            image_document = {
                'filename': image.filename,
                'data': base64_data,
                'quiz_id': quiz_id,
                'score': int(score),
                'image_description': image_description,
                'assignment': assignment
            }
            images_collection.insert_one(image_document)

        flash('Images uploaded successfully', 'success')

        # Retrieve the current quiz and its images
        current_quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})
        images = list(images_collection.find({'quiz_id': quiz_id}))

        if 'upload_and_edit' in request.form:
            flash('Images uploaded successfully', 'success')
            quiz_id = request.form.get('quiz_id')
            return redirect(url_for('edit', quiz_id=quiz_id))
        else:
            # Render the upload_images.html template with the current_quiz and images
            current_quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})
            images = list(images_collection.find({'quiz_id': quiz_id}))
            quizzes = list(quizzes_collection.find())
            return render_template('upload_images.html', current_quiz=current_quiz, images=images, quizzes=quizzes, quiz_id=quiz_id)

@app.route('/create_thumbnail/<image_id>', methods=['POST'])
def create_thumbnail(image_id):
    # Retrieve the original image from the database
    image = images_collection.find_one({'_id': ObjectId(image_id)})
    if not image:
        return 'Image not found', 404

    # Decode the base64 image data
    image_data = base64.b64decode(image['data'])

    # Create a thumbnail
    thumbnail = Image.open(io.BytesIO(image_data))
    thumbnail.thumbnail((128, 128), Image.BICUBIC)

    # Convert the thumbnail to base64
    thumbnail_io = io.BytesIO()
    thumbnail.save(thumbnail_io, format='PNG')
    thumbnail_data = base64.b64encode(thumbnail_io.getvalue()).decode('utf-8')

    # Update the image document in the database with the thumbnail data
    result = images_collection.update_one(
        {'_id': ObjectId(image_id)},
        {'$set': {'thumbnail': thumbnail_data}}
    )

    if result.modified_count == 1:
        return 'Thumbnail created successfully', 200
    else:
        return 'Failed to create thumbnail', 500 

@app.route('/update_image/<image_id>', methods=['POST'])
def update_image(image_id):
    if request.method == 'POST':
        updated_data = request.json
        result = images_collection.update_one({'_id': ObjectId(image_id)}, {'$set': updated_data})
        if result.modified_count == 1:
            return 'Image updated successfully', 200
        else:
            return 'Failed to update image', 500

@app.route('/update_all_images', methods=['POST'])
def update_all_images():
    if request.method == 'POST':
        updated_data = request.json
        # Loop through the updated data and update each image
        for image_id, data in updated_data.items():
            result = images_collection.update_one({'_id': ObjectId(image_id)}, {'$set': data})
            if result.modified_count != 1:
                return 'Failed to update all images', 500
        return 'All images updated successfully', 200

@app.route('/replace_image/<image_id>', methods=['POST'])
def replace_image(image_id):
    if request.method == 'POST':
        file = request.files['file']
        if file:
            image_data = file.read()
            base64_data = base64.b64encode(image_data).decode('utf-8')
            updated_data = {'data': base64_data, 'filename': file.filename}
            result = images_collection.update_one({'_id': ObjectId(image_id)}, {'$set': updated_data})
            if result.modified_count == 1:
                return 'Image replaced successfully'
            else:
                return 'Failed to replace image'
        else:
            return 'No file provided'


@app.route('/gallery/<quiz_id>')
def gallery(quiz_id):
    try:
        # Find the current quiz based on the quiz_id
        current_quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})
        if current_quiz is None:
            app.logger.error(f"Quiz with ID {quiz_id} not found")
            abort(404)

        # Get the images for the current quiz
        images = list(images_collection.find({'quiz_id': quiz_id}))

        # Get the list of all quizzes
        quizzes = list(quizzes_collection.find({}, {'name': 1, '_id': 1}))

        return render_template('gallery.html', images=images, quizzes=quizzes, current_quiz=current_quiz)
    except Exception as e:
        app.logger.error(f"Error in gallery route: {str(e)}")
        abort(500)

@app.route('/lost_images')
def lost_images():
    try:
        # Get all the images
        all_images = list(images_collection.find({}))

        # Get the list of all valid quiz IDs
        valid_quiz_ids = [str(quiz['_id']) for quiz in quizzes_collection.find({}, {'_id': 1})]

        # Filter the images that have an invalid quiz ID
        lost_images = [image for image in all_images if image['quiz_id'] not in valid_quiz_ids]

        # Get the list of all quizzes
        quizzes = list(quizzes_collection.find({}, {'name': 1, '_id': 1}))

        # Pass a placeholder value for current_quiz
        current_quiz = None

        return render_template('lost_images.html', images=lost_images, quizzes=quizzes, current_quiz=current_quiz)

    except Exception as e:
        app.logger.error(f"Error in lost_images route: {str(e)}")
        abort(500)

@app.route('/gallery_partial')
def gallery_partial():
    images = list(images_collection.find())
    quizzes = list(quizzes_collection.find())
    return render_template('gallery_partial.html', images=images, quizzes=quizzes)

@app.route('/image_edit/<image_id>', methods=['GET', 'POST'])
def image_edit(image_id):
    if request.method == 'POST':
        updated_values = request.get_json()
        for key, value in updated_values.items():
            images_collection.update_one(
                {'_id': ObjectId(image_id)},
                {'$set': {key: value}}
            )
        return 'Image updated successfully'
    else:
        image = images_collection.find_one({'_id': ObjectId(image_id)})
        return render_template('image_edit.html', image=image)




@app.route('/delete_gallery_image/<quiz_id>/<image_id>', methods=['GET', 'POST'])
def delete_gallery_image(quiz_id, image_id):
    # Retrieve the current quiz object
    current_quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})

    # Delete the image
    result = images_collection.delete_one({'_id': ObjectId(image_id)})

    if result.deleted_count == 1:
        # Redirect back to the gallery page
        return redirect(url_for('gallery', quiz_id=quiz_id))
    else:
        return 'Failed to delete image'


@app.route('/delete_image/<quiz_id>/<image_id>', methods=['DELETE'])
def delete_image(quiz_id, image_id):
    # Retrieve the current quiz object
    current_quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})

    # Delete the image
    result = images_collection.delete_one({'_id': ObjectId(image_id)})

    if result.deleted_count == 1:
        # Return the quiz name along with the success message
        return jsonify({'success': True, 'quiz_name': current_quiz['name']})
    else:
        return jsonify({'success': False})

    

@app.route('/reset', methods=['GET'])
def reset():
    # Get the current quiz ID from the session
    current_quiz_id = session.get('current_quiz_id')

    # Reset the session data for the current quiz
    session['images_shown'] = 0
    session['current_page'] = 1
    session['current_score'] = 0

    # Redirect the user back to the start page for the current quiz
    return redirect(url_for('start', quiz_id=current_quiz_id))



@app.route('/delete_quiz/<quiz_id>', methods=['GET', 'POST'])
def delete_quiz(quiz_id):
    quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})
    if quiz:
        quiz_name = quiz.get('name', 'Unknown Quiz')
        quizzes_collection.delete_one({'_id': ObjectId(quiz_id)})
        flash(f'Quiz <span style="color: red;">"{quiz_name}"</span> <span style="color: red;">deleted</span> successfully', 'success')  # Flash a success message with colored quiz name and "deleted"
    else:
        flash('Quiz deletion failed. Quiz not found.', 'error')  # Flash an error message if the quiz is not found
    return redirect(url_for('index'))  # Redirect back to the index page


if __name__ == '__main__':
    app.run(debug=True)