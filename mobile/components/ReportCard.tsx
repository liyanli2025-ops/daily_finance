import React from 'react';
import { View, StyleSheet } from 'react-native';
import { Card, Text, Chip, useTheme } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { router } from 'expo-router';

interface Report {
  id: string;
  title: string;
  summary: string;
  report_date: string;
  podcast_status: string;
  podcast_duration?: number;
  created_at: string;
}

interface ReportCardProps {
  report: Report;
}

export default function ReportCard({ report }: ReportCardProps) {
  const theme = useTheme();

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('zh-CN', {
      month: 'short',
      day: 'numeric',
    });
  };

  return (
    <Card
      style={[styles.card, { backgroundColor: theme.colors.surface }]}
      onPress={() => router.push(`/report/${report.id}`)}
    >
      <Card.Content>
        <View style={styles.header}>
          <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
            {formatDate(report.report_date)}
          </Text>
          {report.podcast_status === 'ready' && (
            <Chip
              icon="podcast"
              compact
              style={styles.podcastChip}
              textStyle={{ fontSize: 10, color: theme.colors.secondary }}
            >
              播客
            </Chip>
          )}
        </View>

        <Text variant="titleSmall" style={styles.title} numberOfLines={2}>
          {report.title}
        </Text>

        <Text variant="bodySmall" style={styles.summary} numberOfLines={2}>
          {report.summary}
        </Text>

        <View style={styles.footer}>
          <MaterialCommunityIcons
            name="chevron-right"
            size={20}
            color={theme.colors.outline}
          />
        </View>
      </Card.Content>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: {
    marginBottom: 12,
    borderRadius: 12,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  podcastChip: {
    height: 24,
    backgroundColor: 'rgba(3, 218, 198, 0.15)',
  },
  title: {
    fontWeight: '600',
    marginBottom: 4,
  },
  summary: {
    opacity: 0.7,
    lineHeight: 18,
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    marginTop: 8,
  },
});
