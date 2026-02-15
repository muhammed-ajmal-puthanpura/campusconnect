"""
Database Models - SQLAlchemy ORM
Defines all database tables according to schema requirements
"""

from models import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

class Role(db.Model):
    """User roles table"""
    __tablename__ = 'roles'
    
    role_id = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(50), unique=True, nullable=False)
    
    # Relationships
    users = db.relationship('User', backref='role', lazy=True)
    
    def __repr__(self):
        return f'<Role {self.role_name}>'


class Department(db.Model):
    """Departments table"""
    __tablename__ = 'departments'
    
    dept_id = db.Column(db.Integer, primary_key=True)
    dept_name = db.Column(db.String(100), unique=True, nullable=False)
    
    # Relationships
    users = db.relationship('User', backref='department', lazy=True)
    venues = db.relationship('Venue', backref='department', lazy=True)
    events = db.relationship('Event', backref='department', lazy=True)
    
    def __repr__(self):
        return f'<Department {self.dept_name}>'


class User(db.Model):
    """Users table - handles all user types"""
    __tablename__ = 'users'
    
    user_id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.role_id'), nullable=False)
    dept_id = db.Column(db.Integer, db.ForeignKey('departments.dept_id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expiry_date = db.Column(db.DateTime, nullable=True)
    guest_status = db.Column(db.String(20), default='active')  # active, expired, disabled
    

    
    # Relationships
    organized_events = db.relationship('Event', foreign_keys='Event.organizer_id', backref='organizer', lazy=True)
    approvals = db.relationship('Approval', backref='approver', lazy=True)
    registrations = db.relationship('Registration', backref='student', lazy=True)
    scanned_attendance = db.relationship('Attendance', backref='scanner', lazy=True)
    certificates = db.relationship('Certificate', backref='student', lazy=True)
    feedback = db.relationship('Feedback', backref='student', lazy=True)
    
    def set_password(self, password):
        """Hash and set password"""
        self.password = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify password"""
        return check_password_hash(self.password, password)
    
    def __repr__(self):
        return f'<User {self.email}>'


class Venue(db.Model):
    """Venues table"""
    __tablename__ = 'venues'
    
    venue_id = db.Column(db.Integer, primary_key=True)
    venue_name = db.Column(db.String(100), nullable=False)
    dept_id = db.Column(db.Integer, db.ForeignKey('departments.dept_id'), nullable=True)
    capacity = db.Column(db.Integer, nullable=False)
    
    # Relationships
    events = db.relationship('Event', backref='venue', lazy=True)
    
    def __repr__(self):
        return f'<Venue {self.venue_name}>'


class Event(db.Model):
    """Events table"""
    __tablename__ = 'events'
    
    event_id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    # Database column is named `event_date`; map it to the attribute `date`
    date = db.Column('event_date', db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    venue_id = db.Column(db.Integer, db.ForeignKey('venues.venue_id'), nullable=True)
    dept_id = db.Column(db.Integer, db.ForeignKey('departments.dept_id'), nullable=False)
    # Mode of event: 'online' or 'offline'
    mode = db.Column(db.String(20), default='offline')
    # If online, optional meeting URL
    meeting_url = db.Column(db.String(255), nullable=True)
    # Optional event poster image path
    poster_url = db.Column(db.String(255), nullable=True)
    # Optional certificate template selection
    certificate_template_id = db.Column(db.Integer, db.ForeignKey('certificate_templates.template_id'), nullable=True)
    # Token for public scan URLs
    scan_token = db.Column(db.String(64), nullable=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Guest account fields
    is_guest = db.Column(db.Boolean, default=False)
    expiry_date = db.Column(db.DateTime, nullable=True)
    guest_status = db.Column(db.String(20), default='active')  # active, expired, disabled

    
    # Team event fields
    is_team_event = db.Column(db.Boolean, default=False)
    min_team_size = db.Column(db.Integer, default=1)
    max_team_size = db.Column(db.Integer, default=1)
    # Audience: if True the event is campus-exclusive (students only); otherwise public
    is_campus_exclusive = db.Column(db.Boolean, default=False)
    
    # Prize event field (for events with prizes - applies to both team and individual events)
    has_prizes = db.Column(db.Boolean, default=False)
    # Whether duty leave is provided for this event (visible to students)
    duty_leave_provided = db.Column(db.Boolean, default=False)
    
    # Relationships
    approvals = db.relationship('Approval', backref='event', lazy=True, cascade='all, delete-orphan')
    registrations = db.relationship('Registration', backref='event', lazy=True, cascade='all, delete-orphan')
    certificates = db.relationship('Certificate', backref='event', lazy=True, cascade='all, delete-orphan')
    feedback = db.relationship('Feedback', backref='event', lazy=True, cascade='all, delete-orphan')
    certificate_template = db.relationship('CertificateTemplate', backref='events', lazy=True)
    teams = db.relationship('Team', backref='event', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Event {self.title}>'


class Approval(db.Model):
    """Approvals table - tracks approval workflow"""
    __tablename__ = 'approvals'
    
    approval_id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.event_id'), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    approver_role = db.Column(db.String(50), nullable=False)  # HOD, Principal
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    remarks = db.Column(db.Text)
    approved_at = db.Column(db.DateTime)
    
    def __repr__(self):
        return f'<Approval {self.approval_id} - {self.status}>'


class Registration(db.Model):
    """Registrations table - student event registrations"""
    __tablename__ = 'registrations'
    
    registration_id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.event_id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    qr_code = db.Column(db.String(255), unique=True, nullable=False)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.team_id'), nullable=True)
    
    # Individual prize fields (for non-team events with prizes)
    prize_position = db.Column(db.String(50), nullable=True)  # '1st', '2nd', '3rd', 'Special', etc.
    prize_title = db.Column(db.String(100), nullable=True)  # 'Winner', 'Runner Up', 'Best Performance', etc.
    prize_certificate_template_id = db.Column(db.Integer, db.ForeignKey('certificate_templates.template_id'), nullable=True)
    
    # Relationships
    attendance = db.relationship('Attendance', backref='registration', uselist=False, cascade='all, delete-orphan')
    prize_certificate_template = db.relationship('CertificateTemplate', foreign_keys=[prize_certificate_template_id])
    
    def __repr__(self):
        return f'<Registration {self.registration_id}>'


class Team(db.Model):
    """Teams table - for team events like hackathons"""
    __tablename__ = 'teams'
    
    team_id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.event_id'), nullable=False)
    team_name = db.Column(db.String(100), nullable=False)
    leader_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Guest account fields
    is_guest = db.Column(db.Boolean, default=False)
    expiry_date = db.Column(db.DateTime, nullable=True)
    guest_status = db.Column(db.String(20), default='active')  # active, expired, disabled

    
    # Prize fields
    prize_position = db.Column(db.String(50), nullable=True)  # '1st', '2nd', '3rd', 'Special', etc.
    prize_title = db.Column(db.String(100), nullable=True)  # 'Winner', 'Runner Up', 'Best Innovation', etc.
    prize_certificate_template_id = db.Column(db.Integer, db.ForeignKey('certificate_templates.template_id'), nullable=True)
    
    # Relationships
    leader = db.relationship('User', backref='led_teams', foreign_keys=[leader_id])
    members = db.relationship('Registration', backref='team', lazy=True)
    invitations = db.relationship('TeamInvitation', backref='team', lazy=True, cascade='all, delete-orphan')
    prize_certificate_template = db.relationship('CertificateTemplate', foreign_keys=[prize_certificate_template_id])
    
    def __repr__(self):
        return f'<Team {self.team_name}>'


class TeamInvitation(db.Model):
    """Team invitations - sent by team leader to invite members"""
    __tablename__ = 'team_invitations'
    
    invitation_id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.team_id'), nullable=False)
    invitee_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Guest account fields
    is_guest = db.Column(db.Boolean, default=False)
    expiry_date = db.Column(db.DateTime, nullable=True)
    guest_status = db.Column(db.String(20), default='active')  # active, expired, disabled

    responded_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    invitee = db.relationship('User', backref='team_invitations', foreign_keys=[invitee_id])
    
    def __repr__(self):
        return f'<TeamInvitation {self.invitation_id}>'


class Attendance(db.Model):
    """Attendance table - tracks event attendance via QR scan"""
    __tablename__ = 'attendance'
    
    attendance_id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('registrations.registration_id'), nullable=False, unique=True)
    scan_time = db.Column(db.DateTime, nullable=False)
    scanned_by = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    status = db.Column(db.String(20), default='present')  # present, absent
    
    def __repr__(self):
        return f'<Attendance {self.attendance_id}>'


class Certificate(db.Model):
    """Certificates table - generated certificates"""
    __tablename__ = 'certificates'
    
    certificate_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.event_id'), nullable=False)
    certificate_url = db.Column(db.String(255), nullable=False)
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Certificate {self.certificate_id}>'


class CertificateTemplate(db.Model):
    """Certificate templates uploaded by organizers"""
    __tablename__ = 'certificate_templates'

    template_id = db.Column(db.Integer, primary_key=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    image_url = db.Column(db.String(255), nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    positions = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Guest account fields
    is_guest = db.Column(db.Boolean, default=False)
    expiry_date = db.Column(db.DateTime, nullable=True)
    guest_status = db.Column(db.String(20), default='active')  # active, expired, disabled


    organizer = db.relationship('User', backref='certificate_templates', lazy=True)

    def __repr__(self):
        return f'<CertificateTemplate {self.template_id}>'


class Feedback(db.Model):
    """Feedback table - student feedback and ratings"""
    __tablename__ = 'feedback'
    
    feedback_id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.event_id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    comments = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Feedback {self.feedback_id}>'





class AppConfig(db.Model):
    """Simple key/value storage for admin-configurable settings"""
    __tablename__ = 'app_config'

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f'<AppConfig {self.key}={self.value}>'
