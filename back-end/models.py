from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import json

db = SQLAlchemy()

# Association table for user-organization relationships with roles
user_organization = db.Table('user_organization',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('organization_id', db.Integer, db.ForeignKey('organization.id'), primary_key=True),
    db.Column('role', db.String(20), nullable=False, default='member')  # owner, admin, member
)

# Association table for market editors
market_editors = db.Table('market_editors',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('market_id', db.Integer, db.ForeignKey('market.id'), primary_key=True)
)

# Association table for market viewers
market_viewers = db.Table('market_viewers',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('market_id', db.Integer, db.ForeignKey('market.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    organizations = db.relationship('Organization', secondary=user_organization, 
                                  back_populates='users', lazy='dynamic')
    owned_markets = db.relationship('Market', backref='owner', lazy='dynamic')
    editable_markets = db.relationship('Market', secondary=market_editors, 
                                     back_populates='editors', lazy='dynamic')
    viewable_markets = db.relationship('Market', secondary=market_viewers, 
                                     back_populates='viewers', lazy='dynamic')
    
    def get_id(self):
        return str(self.id)
    
    def get_organization_role(self, organization_id):
        """Get user's role in a specific organization"""
        result = db.session.execute(
            user_organization.select().where(
                user_organization.c.user_id == self.id,
                user_organization.c.organization_id == organization_id
            )
        ).first()
        return result.role if result else None
    
    def has_organization_access(self, organization_id, required_role='member'):
        """Check if user has required role in organization"""
        role = self.get_organization_role(organization_id)
        if not role:
            return False
        
        role_hierarchy = {'owner': 3, 'admin': 2, 'member': 1}
        return role_hierarchy.get(role, 0) >= role_hierarchy.get(required_role, 0)
    
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'organizations': [org.to_dict() for org in self.organizations],
            'markets': [market.name for market in self.owned_markets]
        }

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    users = db.relationship('User', secondary=user_organization, 
                           back_populates='organizations', lazy='dynamic')
    markets = db.relationship('Market', backref='organization', lazy='dynamic')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Market(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    setup_object = db.Column(db.Text)  # JSON string
    modification_list = db.Column(db.Text)  # JSON string
    assignment_object = db.Column(db.Text)  # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    editors = db.relationship('User', secondary=market_editors, 
                            back_populates='editable_markets', lazy='dynamic')
    viewers = db.relationship('User', secondary=market_viewers, 
                            back_populates='viewable_markets', lazy='dynamic')
    vendors = db.relationship('Vendor', backref='market', lazy='dynamic')
    assignments = db.relationship('Assignment', backref='market', lazy='dynamic')
    
    def get_setup_object(self):
        """Parse setup_object JSON string"""
        return json.loads(self.setup_object) if self.setup_object else {}
    
    def set_setup_object(self, setup_obj):
        """Set setup_object as JSON string"""
        self.setup_object = json.dumps(setup_obj) if setup_obj else None
    
    def get_modification_list(self):
        """Parse modification_list JSON string"""
        return json.loads(self.modification_list) if self.modification_list else []
    
    def set_modification_list(self, mod_list):
        """Set modification_list as JSON string"""
        self.modification_list = json.dumps(mod_list) if mod_list else None
    
    def get_assignment_object(self):
        """Parse assignment_object JSON string"""
        return json.loads(self.assignment_object) if self.assignment_object else None
    
    def set_assignment_object(self, assignment_obj):
        """Set assignment_object as JSON string"""
        self.assignment_object = json.dumps(assignment_obj) if assignment_obj else None
    
    def user_can_view(self, user):
        """Check if user can view this market"""
        return (user.id == self.owner_id or 
                user in self.editors or 
                user in self.viewers or
                user.has_organization_access(self.organization_id, 'member'))
    
    def user_can_edit(self, user):
        """Check if user can edit this market"""
        return (user.id == self.owner_id or 
                user in self.editors or
                user.has_organization_access(self.organization_id, 'admin'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'organization_id': self.organization_id,
            'owner': self.owner.email if self.owner else None,
            'editors': [user.email for user in self.editors],
            'viewers': [user.email for user in self.viewers],
            'setupObject': self.get_setup_object(),
            'modificationList': self.get_modification_list(),
            'assignmentObject': self.get_assignment_object(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class Vendor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    market_id = db.Column(db.Integer, db.ForeignKey('market.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    business_name = db.Column(db.String(100))
    product_type = db.Column(db.String(100))
    priority_tier = db.Column(db.String(50))
    location_preference = db.Column(db.String(100))
    section_preference = db.Column(db.String(100))
    application_data = db.Column(db.Text)  # JSON string for additional form data
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    assignments = db.relationship('Assignment', backref='vendor', lazy='dynamic')
    attendance_records = db.relationship('AttendanceRecord', backref='vendor', lazy='dynamic')
    
    def get_application_data(self):
        """Parse application_data JSON string"""
        return json.loads(self.application_data) if self.application_data else {}
    
    def set_application_data(self, app_data):
        """Set application_data as JSON string"""
        self.application_data = json.dumps(app_data) if app_data else None
    
    def to_dict(self):
        return {
            'id': self.id,
            'market_id': self.market_id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'business_name': self.business_name,
            'product_type': self.product_type,
            'priority_tier': self.priority_tier,
            'location_preference': self.location_preference,
            'section_preference': self.section_preference,
            'application_data': self.get_application_data(),
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    market_id = db.Column(db.Integer, db.ForeignKey('market.id'), nullable=False)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'), nullable=False)
    table_number = db.Column(db.String(20))
    location = db.Column(db.String(100))
    section = db.Column(db.String(100))
    market_date = db.Column(db.Date)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    # Relationships
    assigned_by = db.relationship('User', backref='assignments_made')
    
    def to_dict(self):
        return {
            'id': self.id,
            'market_id': self.market_id,
            'vendor_id': self.vendor_id,
            'vendor_name': self.vendor.name if self.vendor else None,
            'table_number': self.table_number,
            'location': self.location,
            'section': self.section,
            'market_date': self.market_date.isoformat() if self.market_date else None,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'assigned_by': self.assigned_by.email if self.assigned_by else None
        }

class AttendanceRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'), nullable=False)
    market_date = db.Column(db.Date, nullable=False)
    check_in_time = db.Column(db.DateTime)
    check_out_time = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='absent')  # present, absent, late
    notes = db.Column(db.Text)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    # Relationships
    recorded_by = db.relationship('User', backref='attendance_records_made')
    
    def to_dict(self):
        return {
            'id': self.id,
            'vendor_id': self.vendor_id,
            'vendor_name': self.vendor.name if self.vendor else None,
            'market_date': self.market_date.isoformat() if self.market_date else None,
            'check_in_time': self.check_in_time.isoformat() if self.check_in_time else None,
            'check_out_time': self.check_out_time.isoformat() if self.check_out_time else None,
            'status': self.status,
            'notes': self.notes,
            'recorded_by': self.recorded_by.email if self.recorded_by else None
        }
