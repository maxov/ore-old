from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, UserManager
from django.core import validators
from django.core.mail import send_mail
from django.db import models
from django.utils.translation import ugettext_lazy as _t
from django.utils import timezone
from django.db.models.signals import post_save

from model_utils.managers import InheritanceManager


EXTENDED_CHAR_REGEX = r'[\w.@+-]+'
EXTENDED_NAME_REGEX = r'^' + EXTENDED_CHAR_REGEX + r'$'
TRIM_NAME_REGEX = r'^' + EXTENDED_CHAR_REGEX + r'([\w.@+ -]*' + EXTENDED_CHAR_REGEX + r')?$'

Q = models.Q


class Namespace(models.Model):

    name = models.CharField('name', max_length=32, unique=True,
                            validators=[
                                validators.RegexValidator(EXTENDED_NAME_REGEX, 'Enter a namespace organization name.', 'invalid')
                            ])

    objects = InheritanceManager()


class RepoUserManager(UserManager):
    def _create_user(self, username, email, password, is_staff, is_superuser, **extra_fields):
        now = timezone.now()
        if not username:
            raise ValueError("The given username must be set")
        email = self.normalize_email(email)
        user = self.model(name=username, email=email, is_staff=is_staff, is_active=True, is_superuser=True, date_joined=now, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class RepoUser(AbstractBaseUser, PermissionsMixin, Namespace):

    # All taken from AbstractUser
    # name from Namespace
    email = models.EmailField('email', blank=True)
    is_staff = models.BooleanField('staff status', default=False,
                                   help_text='Designates whether the user can log into this admin '
                                             'site.')
    is_active = models.BooleanField('active', default=True,
                                    help_text='Designates whether this user should be treated as '
                                              'active. Unselect this instead of deleting accounts.')
    date_joined = models.DateTimeField(_t('creation date'), default=timezone.now)

    objects = RepoUserManager()

    USERNAME_FIELD = 'name'
    REQUIRED_FIELDS = ['email']

    def email_user(self, subject, message, from_email=None, **kwargs):
        send_mail(subject, message, from_email, [self.email], **kwargs)

    def user_has_permission(self, user, perm_slug, project=None):
        return user == self


class Organization(Namespace):

    def user_has_permission(self, user, perm_slug, project=None):
        if self.teams.filter(users=user).filter(Q(is_all_projects=True) | Q(projects=project)).filter(Q(is_owner_team=True) | Q(permissions__slug=perm_slug)).count():
            return True
        return False


class Project(models.Model):

    name = models.CharField('name', max_length=32,
                            validators=[
                                validators.RegexValidator(EXTENDED_NAME_REGEX, 'Enter a valid project name.', 'invalid')
                            ])
    namespace = models.ForeignKey(Namespace, related_name='projects')
    description = models.TextField('description')

    def user_has_permission(self, user, perm_slug):
        if self.teams.filter(users=user).filter(Q(is_owner_team=True) | Q(permissions__slug=perm_slug)).count():
            return True
        return Namespace.objects.get_subclass(id=self.namespace_id).user_has_permission(user, perm_slug, project=self)


class Version(models.Model):

    name = models.CharField('name', max_length=32,
                            validators=[
                                validators.RegexValidator(TRIM_NAME_REGEX, 'Enter a valid version name.', 'invalid')
                            ])
    description = models.TextField('description')
    project = models.ForeignKey(Project, related_name='versions')


class File(models.Model):

    name = models.CharField('name', max_length=32,
                            validators=[
                                validators.RegexValidator(TRIM_NAME_REGEX, 'Enter a valid file name.', 'invalid')
                            ])
    description = models.TextField('description')
    version = models.ForeignKey(Version, related_name='files')


class Permission(models.Model):
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=64, null=False, blank=False)
    description = models.TextField(null=False, blank=False)
    applies_to_project = models.BooleanField(default=True)


class Team(models.Model):
    name = models.CharField('name', max_length=80, null=False, blank=False)
    users = models.ManyToManyField(RepoUser, related_name='%(class)ss')
    permissions = models.ManyToManyField(Permission, related_name='+')
    is_owner_team = models.BooleanField(default=False)

    def check_consistent(self):
        return True

    def make_consistent(self):
        return

    class Meta:
        abstract = True


class OrganizationTeam(Team):
    organization = models.ForeignKey(Organization, related_name='teams')
    projects = models.ManyToManyField(Project, related_name='organizationteams')
    is_all_projects = models.BooleanField(default=False)

    def make_consistent(self):
        self.projects = self.projects.filter(namespace=self.organization)
        self.save()

    def check_consistent(self):
        return self.projects.exclude(namespace=self.organization).count() == 0


class ProjectTeam(Team):
    project = models.ForeignKey(Project, related_name='teams')

    # TODO: we need to check here that if we're a user's project and we're the owner team, that that user is in us!

def create_project_owner_team(sender, instance, created, **kwargs):
    if instance and created:
        owning_namespace = Namespace.objects.get_subclass(id=instance.namespace_id)
        if isinstance(owning_namespace, RepoUser):
            team = ProjectTeam.objects.create(
                    project=instance,
                    is_owner_team=True,
                    name='Owners',
            )
            team.users = [owning_namespace]
            team.save()
post_save.connect(create_project_owner_team, sender=Project)

def create_organization_owner_team(sender, instance, created, **kwargs):
    if instance and created:
        OrganizationTeam.objects.create(
                name='Owners',
                organization=instance,
                is_all_projects=True,
                is_owner_team=True,
        )
post_save.connect(create_organization_owner_team, sender=Organization)
