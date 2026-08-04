# Generated manually to handle the role field change correctly
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_add_global_role_to_user'),
        ('saas', '0001_initial'),
    ]

    operations = [
        # Remove the old global_role field
        migrations.RemoveField(
            model_name='user',
            name='global_role',
        ),
        # Remove the old role field (CharField) if it exists
        migrations.RemoveField(
            model_name='user',
            name='role',
        ),
        # Add the new role field as a ForeignKey
        migrations.AddField(
            model_name='user',
            name='role',
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='users',
                to='saas.role',
                verbose_name='系统角色'
            ),
        ),
    ]
