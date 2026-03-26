import React, { useState } from 'react';
import { View, ScrollView, StyleSheet, Alert } from 'react-native';
import {
  Text,
  List,
  Switch,
  Divider,
  useTheme,
  Button,
  Dialog,
  Portal,
  RadioButton,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useSettingsStore } from '@/stores/settingsStore';

export default function SettingsScreen() {
  const theme = useTheme();
  const {
    notificationEnabled,
    reportHour,
    reportMinute,
    defaultPlaybackRate,
    autoDownload,
    followMarkets,
    setNotificationEnabled,
    setReportTime,
    setDefaultPlaybackRate,
    setAutoDownload,
    setFollowMarkets,
  } = useSettingsStore();

  const [timeDialogVisible, setTimeDialogVisible] = useState(false);
  const [rateDialogVisible, setRateDialogVisible] = useState(false);
  const [selectedHour, setSelectedHour] = useState(reportHour);
  const [selectedMinute, setSelectedMinute] = useState(reportMinute);

  const formatTime = (hour: number, minute: number) => {
    return `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
  };

  const handleSaveTime = () => {
    setReportTime(selectedHour, selectedMinute);
    setTimeDialogVisible(false);
  };

  const playbackRates = [
    { value: 0.75, label: '0.75x' },
    { value: 1, label: '1x (正常)' },
    { value: 1.25, label: '1.25x' },
    { value: 1.5, label: '1.5x' },
    { value: 2, label: '2x' },
  ];

  return (
    <ScrollView style={[styles.container, { backgroundColor: theme.colors.background }]}>
      {/* 推送设置 */}
      <List.Section>
        <List.Subheader style={{ color: theme.colors.primary }}>
          推送设置
        </List.Subheader>

        <List.Item
          title="开启推送通知"
          description="在报告生成后接收通知"
          left={(props) => <List.Icon {...props} icon="bell-outline" />}
          right={() => (
            <Switch
              value={notificationEnabled}
              onValueChange={setNotificationEnabled}
              color={theme.colors.primary}
            />
          )}
          style={styles.listItem}
        />

        <List.Item
          title="推送时间"
          description={`每天 ${formatTime(reportHour, reportMinute)}`}
          left={(props) => <List.Icon {...props} icon="clock-outline" />}
          onPress={() => setTimeDialogVisible(true)}
          style={styles.listItem}
          right={(props) => <List.Icon {...props} icon="chevron-right" />}
        />
      </List.Section>

      <Divider style={styles.divider} />

      {/* 内容偏好 */}
      <List.Section>
        <List.Subheader style={{ color: theme.colors.primary }}>
          内容偏好
        </List.Subheader>

        <List.Item
          title="关注 A股"
          description="接收 A股相关新闻和分析"
          left={(props) => <List.Icon {...props} icon="alpha-a-box" />}
          right={() => (
            <Switch
              value={followMarkets.includes('A')}
              onValueChange={(value) => {
                const markets = value
                  ? [...followMarkets, 'A']
                  : followMarkets.filter((m) => m !== 'A');
                setFollowMarkets(markets);
              }}
              color={theme.colors.primary}
            />
          )}
          style={styles.listItem}
        />

        <List.Item
          title="关注港股"
          description="接收港股相关新闻和分析"
          left={(props) => <List.Icon {...props} icon="alpha-h-box" />}
          right={() => (
            <Switch
              value={followMarkets.includes('HK')}
              onValueChange={(value) => {
                const markets = value
                  ? [...followMarkets, 'HK']
                  : followMarkets.filter((m) => m !== 'HK');
                setFollowMarkets(markets);
              }}
              color={theme.colors.primary}
            />
          )}
          style={styles.listItem}
        />

      </List.Section>

      <Divider style={styles.divider} />

      {/* 播客设置 */}
      <List.Section>
        <List.Subheader style={{ color: theme.colors.primary }}>
          播客设置
        </List.Subheader>

        <List.Item
          title="默认播放倍速"
          description={`${defaultPlaybackRate}x`}
          left={(props) => <List.Icon {...props} icon="speedometer" />}
          onPress={() => setRateDialogVisible(true)}
          style={styles.listItem}
          right={(props) => <List.Icon {...props} icon="chevron-right" />}
        />

        <List.Item
          title="自动下载"
          description="Wi-Fi 下自动下载新播客"
          left={(props) => <List.Icon {...props} icon="download-outline" />}
          right={() => (
            <Switch
              value={autoDownload}
              onValueChange={setAutoDownload}
              color={theme.colors.primary}
            />
          )}
          style={styles.listItem}
        />
      </List.Section>

      <Divider style={styles.divider} />

      {/* 高级设置 */}
      <List.Section>
        <List.Subheader style={{ color: theme.colors.primary }}>
          高级设置
        </List.Subheader>

        <List.Item
          title="API 配置"
          description="配置后端服务地址"
          left={(props) => <List.Icon {...props} icon="api" />}
          onPress={() => Alert.alert('提示', '此功能正在开发中')}
          style={styles.listItem}
          right={(props) => <List.Icon {...props} icon="chevron-right" />}
        />

        <List.Item
          title="清除缓存"
          description="清除本地缓存数据"
          left={(props) => <List.Icon {...props} icon="delete-outline" />}
          onPress={() => Alert.alert('确认', '确定要清除所有缓存吗？', [
            { text: '取消', style: 'cancel' },
            { text: '确定', onPress: () => Alert.alert('提示', '缓存已清除') },
          ])}
          style={styles.listItem}
          right={(props) => <List.Icon {...props} icon="chevron-right" />}
        />
      </List.Section>

      <Divider style={styles.divider} />

      {/* 关于 */}
      <List.Section>
        <List.Subheader style={{ color: theme.colors.primary }}>
          关于
        </List.Subheader>

        <List.Item
          title="版本"
          description="1.0.0 (MVP)"
          left={(props) => <List.Icon {...props} icon="information-outline" />}
          style={styles.listItem}
        />

        <List.Item
          title="使用说明"
          description="了解如何使用此应用"
          left={(props) => <List.Icon {...props} icon="help-circle-outline" />}
          onPress={() => Alert.alert('使用说明', '每天早上 6 点，系统会自动生成财经日报和播客。您可以在首页查看报告，在播客页面收听音频，在自选股页面追踪您感兴趣的股票。')}
          style={styles.listItem}
          right={(props) => <List.Icon {...props} icon="chevron-right" />}
        />

        <List.Item
          title="反馈建议"
          description="告诉我们您的想法"
          left={(props) => <List.Icon {...props} icon="message-outline" />}
          onPress={() => Alert.alert('提示', '反馈功能正在开发中')}
          style={styles.listItem}
          right={(props) => <List.Icon {...props} icon="chevron-right" />}
        />
      </List.Section>

      <View style={{ height: 32 }} />

      {/* 时间选择对话框 */}
      <Portal>
        <Dialog visible={timeDialogVisible} onDismiss={() => setTimeDialogVisible(false)}>
          <Dialog.Title>设置推送时间</Dialog.Title>
          <Dialog.Content>
            <View style={styles.timePickerContainer}>
              <View style={styles.timePicker}>
                <Text variant="bodyMedium" style={{ marginBottom: 8 }}>小时</Text>
                <ScrollView style={styles.timeScroll}>
                  {Array.from({ length: 24 }, (_, i) => (
                    <Button
                      key={i}
                      mode={selectedHour === i ? 'contained' : 'text'}
                      compact
                      onPress={() => setSelectedHour(i)}
                      style={{ marginVertical: 2 }}
                    >
                      {i.toString().padStart(2, '0')}
                    </Button>
                  ))}
                </ScrollView>
              </View>
              <Text variant="headlineMedium" style={{ marginHorizontal: 8 }}>:</Text>
              <View style={styles.timePicker}>
                <Text variant="bodyMedium" style={{ marginBottom: 8 }}>分钟</Text>
                <ScrollView style={styles.timeScroll}>
                  {[0, 15, 30, 45].map((m) => (
                    <Button
                      key={m}
                      mode={selectedMinute === m ? 'contained' : 'text'}
                      compact
                      onPress={() => setSelectedMinute(m)}
                      style={{ marginVertical: 2 }}
                    >
                      {m.toString().padStart(2, '0')}
                    </Button>
                  ))}
                </ScrollView>
              </View>
            </View>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setTimeDialogVisible(false)}>取消</Button>
            <Button onPress={handleSaveTime}>确定</Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>

      {/* 倍速选择对话框 */}
      <Portal>
        <Dialog visible={rateDialogVisible} onDismiss={() => setRateDialogVisible(false)}>
          <Dialog.Title>默认播放倍速</Dialog.Title>
          <Dialog.Content>
            <RadioButton.Group
              onValueChange={(value) => {
                setDefaultPlaybackRate(parseFloat(value));
                setRateDialogVisible(false);
              }}
              value={defaultPlaybackRate.toString()}
            >
              {playbackRates.map((rate) => (
                <RadioButton.Item
                  key={rate.value}
                  label={rate.label}
                  value={rate.value.toString()}
                />
              ))}
            </RadioButton.Group>
          </Dialog.Content>
        </Dialog>
      </Portal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  listItem: {
    paddingHorizontal: 16,
  },
  divider: {
    marginVertical: 8,
  },
  timePickerContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
  },
  timePicker: {
    alignItems: 'center',
    width: 80,
  },
  timeScroll: {
    maxHeight: 200,
  },
});
