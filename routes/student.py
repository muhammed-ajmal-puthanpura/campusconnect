"""
Student Routes - Dashboard, Event Registration, Certificates, Feedback
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from models.models import Event, Registration, Attendance, Certificate, Feedback, User, Venue, Team, TeamInvitation
from models import db
from datetime import datetime, date
from sqlalchemy import or_
from utils.qr_utils import generate_qr_code
from functools import wraps
import os

bp = Blueprint('student', __name__, url_prefix='/student')

def student_required(f):
    """Decorator to require student login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Allow regular students and guest users (role-based or legacy flag)
        if 'user_id' not in session or not (
            session.get('role_name', '').lower() in ('student', 'guest') or session.get('is_guest')
        ):
            flash('Access denied', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@bp.route('/dashboard')
@student_required
def dashboard():
    """Student dashboard - view upcoming approved events"""
    # Get upcoming approved events
    today = date.today()
    # For guests, hide campus-exclusive events
    base_query = Event.query.filter(
        Event.status == 'approved',
        Event.date >= today
    )
    if session.get('role_name', '').lower() == 'guest' or session.get('is_guest'):
        base_query = base_query.filter(Event.is_campus_exclusive == False)
    upcoming_events = base_query.order_by(Event.date, Event.start_time).all()
    
    # Get student's registrations
    student_id = session['user_id']
    registrations = Registration.query.filter_by(student_id=student_id).all()
    registered_event_ids = [r.event_id for r in registrations]
    
    # Get past attended events (include events happening today so attendance marked today shows up)
    past_events = db.session.query(Event).join(Registration).join(Attendance).filter(
        Registration.student_id == student_id,
        Event.date <= today
    ).order_by(Event.date.desc()).all()
    
    # Compute attended event ids for counts and UI
    attended_rows = db.session.query(Registration.event_id).join(Attendance).filter(
        Registration.student_id == student_id
    ).all()
    attended_event_ids = {row[0] for row in attended_rows}
    
    # Get pending team invitations count
    pending_invitations_count = TeamInvitation.query.filter_by(
        invitee_id=student_id,
        status='pending'
    ).count()
    
    # Build notifications for student
    notifications = []
    now = datetime.now()
    from datetime import timedelta
    week_ago = now - timedelta(days=7)
    
    # 1. New certificates (issued in last 7 days)
    new_certificates = Certificate.query.filter(
        Certificate.student_id == student_id,
        Certificate.issued_at >= week_ago
    ).order_by(Certificate.issued_at.desc()).all()
    
    for cert in new_certificates:
        event = Event.query.get(cert.event_id)
        if event:
            notifications.append({
                'type': 'certificate',
                'icon': 'ph-certificate',
                'message': f'🎉 Hooray! Your certificate for "{event.title}" is ready!',
                'link': url_for('student.my_certificates'),
                'time': cert.issued_at
            })
    
    # 2. Events awaiting feedback (attended but no feedback given)
    attended_event_ids_list = list(attended_event_ids)
    
    # Get events where student attended but hasn't given feedback
    feedback_given = db.session.query(Feedback.event_id).filter(
        Feedback.student_id == student_id
    ).all()
    feedback_event_ids = {f[0] for f in feedback_given}
    
    events_needing_feedback = []
    for event_id in attended_event_ids_list:
        if event_id not in feedback_event_ids:
            event = Event.query.get(event_id)
            if event:
                # Only show feedback prompt for events that ended (not ongoing)
                try:
                    event_end = datetime.combine(event.date, event.end_time)
                    if now > event_end:
                        events_needing_feedback.append(event)
                except:
                    pass
    
    for event in events_needing_feedback[:3]:  # Limit to 3 feedback prompts
        notifications.append({
            'type': 'feedback',
            'icon': 'ph-chat-teardrop-text',
            'message': f'📝 How was "{event.title}"? Share your feedback!',
            'link': url_for('student.submit_feedback', event_id=event.event_id),
            'time': datetime.combine(event.date, event.end_time) if event.date else now
        })
    
    # 3. Pending team invitations
    pending_invitations = TeamInvitation.query.filter_by(
        invitee_id=student_id,
        status='pending'
    ).order_by(TeamInvitation.created_at.desc()).limit(3).all()
    
    for inv in pending_invitations:
        team = Team.query.get(inv.team_id)
        if team:
            event = Event.query.get(team.event_id)
            if event:
                notifications.append({
                    'type': 'invitation',
                    'icon': 'ph-user-plus',
                    'message': f'👋 You\'ve been invited to join team "{team.team_name}" for "{event.title}"!',
                    'link': url_for('student.team_invitations'),
                    'time': inv.created_at
                })
    
    # 4. Upcoming registered events (reminder)
    for reg in registrations:
        event = Event.query.get(reg.event_id)
        if event and event.date:
            days_until = (event.date - today).days
            if 0 <= days_until <= 2:  # Event is today, tomorrow, or day after
                if days_until == 0:
                    time_msg = "today"
                elif days_until == 1:
                    time_msg = "tomorrow"
                else:
                    time_msg = f"in {days_until} days"
                
                notifications.append({
                    'type': 'reminder',
                    'icon': 'ph-calendar-check',
                    'message': f'📅 Reminder: "{event.title}" is {time_msg} at {event.start_time.strftime("%H:%M")}!',
                    'link': url_for('student.my_registrations'),
                    'time': datetime.combine(event.date, event.start_time)
                })
    
    # Sort notifications by time (most recent/urgent first) and limit
    notifications.sort(key=lambda x: x.get('time') or now, reverse=True)
    notifications = notifications[:5]

    return render_template('student/dashboard.html', 
                         upcoming_events=upcoming_events,
                         registered_event_ids=registered_event_ids,
                         past_events=past_events,
                         attended_event_ids=attended_event_ids,
                         pending_invitations_count=pending_invitations_count,
                         notifications=notifications)


@bp.route('/events')
@student_required
def events():
    """View all approved upcoming events"""
    today = date.today()
    organizer_filter = request.args.get('organizer', '')
    mode_filter = request.args.get('mode', '')
    search_query = request.args.get('q', '').strip()

    # For guests, hide campus-exclusive events
    query = Event.query.filter(
        Event.status == 'approved',
        Event.date >= today
    )
    if session.get('role_name', '').lower() == 'guest' or session.get('is_guest'):
        query = query.filter(Event.is_campus_exclusive == False)

    if organizer_filter:
        query = query.filter_by(organizer_id=int(organizer_filter))

    if mode_filter:
        query = query.filter_by(mode=mode_filter)

    if search_query:
        query = query.filter(Event.title.ilike(f"%{search_query}%"))

    events = query.order_by(Event.date, Event.start_time).all()
    
    # Get student's registrations and attended events
    student_id = session['user_id']
    registrations = Registration.query.filter_by(student_id=student_id).all()
    registered_event_ids = [r.event_id for r in registrations]

    # Compute attended event ids for this student but only for events that have ended
    now = datetime.now()
    attended_rows = db.session.query(Registration.event_id, Event.date, Event.end_time).join(Attendance).join(Event, Event.event_id==Registration.event_id).filter(
        Registration.student_id == student_id
    ).all()
    attended_event_ids = set()
    for row in attended_rows:
        ev_date = row[1]
        ev_end = row[2]
        try:
            ev_end_dt = datetime.combine(ev_date, ev_end)
            if now >= ev_end_dt:
                attended_event_ids.add(row[0])
        except Exception:
            # If any data missing, include conservatively
            attended_event_ids.add(row[0])

    organizers = User.query.join(User.role).filter(
        or_(
            User.role.has(role_name='Event Organizer'),
            User.role.has(role_name='Organizer')
        )
    ).order_by(User.full_name.asc()).all()
    
    return render_template('student/events.html', 
                         events=events,
                         registered_event_ids=registered_event_ids,
                         attended_event_ids=attended_event_ids,
                         organizers=organizers,
                         organizer_filter=organizer_filter,
                         mode_filter=mode_filter,
                         search_query=search_query)


@bp.route('/register/<int:event_id>', methods=['POST'])
@student_required
def register_event(event_id):
    """Register for an event"""
    student_id = session['user_id']
    
    # Check if event exists and is approved
    event = Event.query.get_or_404(event_id)
    if event.status != 'approved':
        flash('This event is not open for registration', 'error')
        return redirect(url_for('student.events'))
    
    # Check if already registered
    existing = Registration.query.filter_by(
        event_id=event_id,
        student_id=student_id
    ).first()
    
    if existing:
        flash('You are already registered for this event', 'warning')
        return redirect(url_for('student.events'))
    
    # If team event, redirect to team registration page
    if event.is_team_event:
        return redirect(url_for('student.team_register', event_id=event_id))
    
    # Create registration for individual event
    registration = Registration(
        event_id=event_id,
        student_id=student_id,
        qr_code='temp'  # Will be updated
    )
    db.session.add(registration)
    db.session.commit()
    
    # Generate QR code
    qr_data, qr_image = generate_qr_code(
        registration.registration_id,
        event_id,
        student_id
    )
    
    # Update QR code
    registration.qr_code = qr_data
    db.session.commit()

    flash('Successfully registered for the event!', 'success')
    return redirect(url_for('student.my_registrations'))


@bp.route('/team-register/<int:event_id>', methods=['GET', 'POST'])
@student_required
def team_register(event_id):
    """Register for a team event - create team or join existing"""
    student_id = session['user_id']
    student = User.query.get(student_id)
    event = Event.query.get_or_404(event_id)
    
    if not event.is_team_event:
        return redirect(url_for('student.register_event', event_id=event_id))
    
    if event.status != 'approved':
        flash('This event is not open for registration', 'error')
        return redirect(url_for('student.events'))
    
    # Check if already registered
    existing = Registration.query.filter_by(
        event_id=event_id,
        student_id=student_id
    ).first()
    
    if existing:
        flash('You are already registered for this event', 'warning')
        return redirect(url_for('student.my_registrations'))
    
    if request.method == 'POST':
        team_name = request.form.get('team_name', '').strip()
        
        if not team_name:
            flash('Team name is required', 'error')
            return redirect(url_for('student.team_register', event_id=event_id))
        
        # Check if team name already exists for this event
        existing_team = Team.query.filter_by(event_id=event_id, team_name=team_name).first()
        if existing_team:
            flash('A team with this name already exists for this event', 'error')
            return redirect(url_for('student.team_register', event_id=event_id))
        
        # Create team
        team = Team(
            event_id=event_id,
            team_name=team_name,
            leader_id=student_id
        )
        db.session.add(team)
        db.session.commit()
        
        # Register team leader
        registration = Registration(
            event_id=event_id,
            student_id=student_id,
            team_id=team.team_id,
            qr_code='temp'
        )
        db.session.add(registration)
        db.session.commit()
        
        # Generate QR code
        qr_data, qr_image = generate_qr_code(
            registration.registration_id,
            event_id,
            student_id
        )
        registration.qr_code = qr_data
        db.session.commit()
        
        flash(f'Team "{team_name}" created! You can now invite team members.', 'success')
        return redirect(url_for('student.manage_team', team_id=team.team_id))
    
    return render_template('student/team_register.html', event=event, student=student)


@bp.route('/team/<int:team_id>')
@student_required
def manage_team(team_id):
    """Manage team - invite members, view status"""
    student_id = session['user_id']
    team = Team.query.get_or_404(team_id)
    event = team.event
    
    # Check if user is team leader or member
    is_leader = team.leader_id == student_id
    is_member = Registration.query.filter_by(
        event_id=event.event_id,
        student_id=student_id,
        team_id=team_id
    ).first() is not None
    
    if not is_leader and not is_member:
        flash('You are not a member of this team', 'error')
        return redirect(url_for('student.my_registrations'))
    
    # Get team members
    members = Registration.query.filter_by(team_id=team_id).all()
    
    # Get pending invitations
    pending_invitations = TeamInvitation.query.filter_by(
        team_id=team_id,
        status='pending'
    ).all()
    
    return render_template('student/manage_team.html',
                         team=team,
                         event=event,
                         members=members,
                         pending_invitations=pending_invitations,
                         is_leader=is_leader)


@bp.route('/team/<int:team_id>/invite', methods=['POST'])
@student_required
def invite_member(team_id):
    """Invite a student to join the team"""
    student_id = session['user_id']
    team = Team.query.get_or_404(team_id)
    
    # Only team leader can invite
    if team.leader_id != student_id:
        flash('Only team leader can invite members', 'error')
        return redirect(url_for('student.manage_team', team_id=team_id))
    
    # Check team size limit
    current_members = Registration.query.filter_by(team_id=team_id).count()
    pending_count = TeamInvitation.query.filter_by(team_id=team_id, status='pending').count()
    
    if current_members >= team.event.max_team_size:
        flash(f'Team already has maximum {team.event.max_team_size} members', 'error')
        return redirect(url_for('student.manage_team', team_id=team_id))
    
    username = request.form.get('username', '').strip()
    
    if not username:
        flash('Username is required', 'error')
        return redirect(url_for('student.manage_team', team_id=team_id))
    
    # Find user by username
    invitee = User.query.filter_by(username=username).first()
    if not invitee:
        flash(f'User "{username}" not found', 'error')
        return redirect(url_for('student.manage_team', team_id=team_id))
    
    # Allow inviting students and guests (role-based)
    role_lower = (invitee.role.role_name or '').strip().lower() if invitee.role else ''
    is_guest_invitee = role_lower == 'guest'
    if not (role_lower == 'student' or is_guest_invitee):
        flash('You can only invite students or guest users by username', 'error')
        return redirect(url_for('student.manage_team', team_id=team_id))
    
    # Can't invite yourself
    if invitee.user_id == student_id:
        flash('You cannot invite yourself', 'error')
        return redirect(url_for('student.manage_team', team_id=team_id))
    
    # Check if already registered for this event
    existing_reg = Registration.query.filter_by(
        event_id=team.event_id,
        student_id=invitee.user_id
    ).first()
    if existing_reg:
        flash(f'{invitee.full_name} is already registered for this event', 'error')
        return redirect(url_for('student.manage_team', team_id=team_id))
    
    # Check if already invited
    existing_invite = TeamInvitation.query.filter_by(
        team_id=team_id,
        invitee_id=invitee.user_id,
        status='pending'
    ).first()
    if existing_invite:
        flash(f'{invitee.full_name} already has a pending invitation', 'warning')
        return redirect(url_for('student.manage_team', team_id=team_id))
    
    # Create invitation
    invitation = TeamInvitation(
        team_id=team_id,
        invitee_id=invitee.user_id,
        status='pending'
    )
    db.session.add(invitation)
    db.session.commit()
    
    flash(f'Invitation sent to {invitee.full_name}!', 'success')
    return redirect(url_for('student.manage_team', team_id=team_id))


@bp.route('/team-invitations')
@student_required
def team_invitations():
    """View pending team invitations"""
    student_id = session['user_id']
    
    invitations = TeamInvitation.query.filter_by(
        invitee_id=student_id,
        status='pending'
    ).order_by(TeamInvitation.created_at.desc()).all()
    
    return render_template('student/team_invitations.html', invitations=invitations)


@bp.route('/team-invitation/<int:invitation_id>/<action>', methods=['POST'])
@student_required
def respond_invitation(invitation_id, action):
    """Accept or reject team invitation"""
    student_id = session['user_id']
    
    invitation = TeamInvitation.query.get_or_404(invitation_id)
    
    if invitation.invitee_id != student_id:
        flash('Invalid invitation', 'error')
        return redirect(url_for('student.team_invitations'))
    
    if invitation.status != 'pending':
        flash('This invitation has already been responded to', 'warning')
        return redirect(url_for('student.team_invitations'))
    
    team = invitation.team
    event = team.event
    
    if action == 'accept':
        # Check if already registered for this event
        existing = Registration.query.filter_by(
            event_id=event.event_id,
            student_id=student_id
        ).first()
        if existing:
            flash('You are already registered for this event', 'error')
            invitation.status = 'rejected'
            invitation.responded_at = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('student.team_invitations'))
        
        # Check team size
        current_members = Registration.query.filter_by(team_id=team.team_id).count()
        if current_members >= event.max_team_size:
            flash('Team is already full', 'error')
            invitation.status = 'rejected'
            invitation.responded_at = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('student.team_invitations'))
        
        # Accept invitation - create registration
        registration = Registration(
            event_id=event.event_id,
            student_id=student_id,
            team_id=team.team_id,
            qr_code='temp'
        )
        db.session.add(registration)
        db.session.commit()
        
        # Generate QR code
        qr_data, qr_image = generate_qr_code(
            registration.registration_id,
            event.event_id,
            student_id
        )
        registration.qr_code = qr_data
        
        invitation.status = 'accepted'
        invitation.responded_at = datetime.utcnow()
        db.session.commit()
        
        flash(f'You have joined team "{team.team_name}"!', 'success')
        return redirect(url_for('student.manage_team', team_id=team.team_id))
    
    elif action == 'reject':
        invitation.status = 'rejected'
        invitation.responded_at = datetime.utcnow()
        db.session.commit()
        flash('Invitation rejected', 'info')
    
    return redirect(url_for('student.team_invitations'))


@bp.route('/my-registrations')
@student_required
def my_registrations():
    """View my event registrations"""
    student_id = session['user_id']
    
    # Get all registrations with QR codes
    search_query = request.args.get('q', '').strip()
    registrations_query = Registration.query.filter_by(student_id=student_id)

    if search_query:
        registrations_query = registrations_query.join(Event).filter(
            Event.title.ilike(f"%{search_query}%")
        )

    registrations = registrations_query.order_by(Registration.registered_at.desc()).all()
    
    # Generate QR images for display
    registration_data = []
    for reg in registrations:
        # Generate QR image from stored data
        from utils.qr_utils import generate_qr_image
        qr_image = generate_qr_image(reg.qr_code)
        
        # Check attendance and only mark as attended if event has ended
        attendance = Attendance.query.filter_by(registration_id=reg.registration_id).first()
        attended_flag = bool(attendance)

        registration_data.append({
            'registration': reg,
            'event': reg.event,
            'qr_image': qr_image,
            'attended': attended_flag
        })

    return render_template('student/my_registrations.html', 
                         registration_data=registration_data,
                         search_query=search_query)


@bp.route('/my-certificates')
@student_required
def my_certificates():
    """View and download certificates"""
    from models.models import Team
    student_id = session['user_id']

    search_query = request.args.get('q', '').strip()
    certificates_query = Certificate.query.filter_by(student_id=student_id)

    if search_query:
        certificates_query = certificates_query.join(Event).filter(
            Event.title.ilike(f"%{search_query}%")
        )

    certificates = certificates_query.order_by(
        Certificate.issued_at.desc()
    ).all()
    
    # Add prize info to certificates
    for cert in certificates:
        cert.prize_text = None
        # Check if this was a team event and if the student's team won a prize
        if cert.event.is_team_event:
            # Find the student's registration for this event (which has team info)
            registration = Registration.query.filter_by(
                event_id=cert.event_id,
                student_id=student_id
            ).first()
            
            if registration and registration.team and registration.team.prize_position:
                team = registration.team
                if team.prize_position != 'Participant':
                    if team.prize_title:
                        cert.prize_text = f"{team.prize_position} - {team.prize_title}"
                    else:
                        cert.prize_text = f"{team.prize_position} Place"
        else:
            # Check for individual prize (non-team event)
            registration = Registration.query.filter_by(
                event_id=cert.event_id,
                student_id=student_id
            ).first()
            
            if registration and registration.prize_position:
                if registration.prize_position != 'Participant':
                    if registration.prize_title:
                        cert.prize_text = f"{registration.prize_position} - {registration.prize_title}"
                    else:
                        cert.prize_text = f"{registration.prize_position} Place"
    
    return render_template('student/certificates.html', 
                           certificates=certificates,
                           search_query=search_query)


@bp.route('/download-certificate/<int:certificate_id>')
@student_required
def download_certificate(certificate_id):
    """Download certificate PDF"""
    student_id = session['user_id']
    
    certificate = Certificate.query.filter_by(
        certificate_id=certificate_id,
        student_id=student_id
    ).first_or_404()
    
    # Get full path
    cert_path = os.path.join('static', certificate.certificate_url)
    
    if os.path.exists(cert_path):
        return send_file(cert_path, as_attachment=True)
    else:
        flash('Certificate file not found', 'error')
        return redirect(url_for('student.my_certificates'))


@bp.route('/submit-feedback/<int:event_id>', methods=['GET', 'POST'])
@student_required
def submit_feedback(event_id):
    """Submit feedback for attended event"""
    student_id = session['user_id']
    
    # Check if student attended the event
    registration = Registration.query.filter_by(
        event_id=event_id,
        student_id=student_id
    ).first()
    
    if not registration:
        flash('You must be registered for the event to submit feedback', 'error')
        return redirect(url_for('student.dashboard'))
    
    attendance = Attendance.query.filter_by(registration_id=registration.registration_id).first()
    
    if not attendance:
        flash('You must attend the event to submit feedback', 'error')
        return redirect(url_for('student.dashboard'))

    # Only allow feedback after the event ends
    try:
        event = Event.query.get(event_id)
        event_end_dt = datetime.combine(event.date, event.end_time)
        if datetime.now() < event_end_dt:
            flash('Feedback is available only after the event has ended', 'error')
            return redirect(url_for('student.dashboard'))
    except Exception:
        # If we cannot determine event end, disallow feedback to be safe
        flash('Feedback is available only after the event has ended', 'error')
        return redirect(url_for('student.dashboard'))
    
    # Check if feedback already submitted
    existing_feedback = Feedback.query.filter_by(
        event_id=event_id,
        student_id=student_id
    ).first()
    
    if request.method == 'POST':
        rating = request.form.get('rating')
        comments = request.form.get('comments')
        
        if existing_feedback:
            # Update existing feedback
            existing_feedback.rating = int(rating)
            existing_feedback.comments = comments
        else:
            # Create new feedback
            feedback = Feedback(
                event_id=event_id,
                student_id=student_id,
                rating=int(rating),
                comments=comments
            )
            db.session.add(feedback)
        
        db.session.commit()
        flash('Feedback submitted successfully!', 'success')
        return redirect(url_for('student.dashboard'))
    
    event = Event.query.get_or_404(event_id)
    return render_template('student/feedback.html', 
                         event=event, 
                         existing_feedback=existing_feedback)
