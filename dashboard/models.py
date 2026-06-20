from companies.models import Team as BaseTeam


class Team(BaseTeam):
    class Meta:
        proxy = True
        ordering = ['-created_at']
        verbose_name = 'Team'
        verbose_name_plural = 'Teams'
